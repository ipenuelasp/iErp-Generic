"""
Motor central de inventario.

Todos los módulos (recepciones, traspasos, producción, kits, ventas)
mueven stock a través de registrar_movimiento(), garantizando que
Existencia y el kardex (MovimientoInventario) siempre estén sincronizados.
"""
import decimal

from django.db import transaction

from .models import Existencia, MovimientoInventario, Lote, NumeroSerie


@transaction.atomic
def mover_orden_a_personal(*, orden, usuario, hacia_personal=True):
    """Traspasa el stock recibido de una orden entre su almacén normal y el
    almacén marcado como 'uso personal' (Almacen.es_uso_personal).

    - hacia_personal=True: saca el stock de la ubicación donde se recibió y lo
      mete al almacén de uso personal.
    - hacia_personal=False: lo regresa a la ubicación original de la recepción.

    Solo mueve lo que esté disponible (lo ya vendido/movido se omite).
    Devuelve (lineas_movidas, faltantes) — faltantes = líneas que no se pudieron
    mover completas porque el stock ya no estaba donde se esperaba.
    """
    from .models import Almacen, Ubicacion, DetalleRecepcion

    personal = Almacen.objects.filter(
        empresa=orden.empresa, sucursal=orden.sucursal_destino,
        es_uso_personal=True, activo=True).first()
    if not personal:
        raise ValueError(
            "No hay un almacén marcado como 'uso personal' en esta sucursal. "
            "Crea o edita un almacén y activa la casilla 'Es almacén de uso personal'.")
    ubic_personal = Ubicacion.objects.filter(almacen=personal, activa=True).first()
    if not ubic_personal:
        raise ValueError(
            f"El almacén de uso personal '{personal.nombre}' no tiene ubicaciones. "
            "Agrégale al menos una ubicación.")

    detalles = DetalleRecepcion.objects.filter(
        recepcion__orden_compra=orden).select_related('producto', 'ubicacion')
    movidas = 0
    faltantes = 0
    for det in detalles:
        origen = det.ubicacion if hacia_personal else ubic_personal
        destino = ubic_personal if hacia_personal else det.ubicacion
        if origen.id == destino.id:
            continue
        movido = _traspasar_existencias(
            empresa=orden.empresa, sucursal=orden.sucursal_destino, producto=det.producto,
            origen_ubic=origen, destino_ubic=destino, cantidad=det.cantidad_recibida,
            usuario=usuario, referencia=f"USO PERSONAL {orden.folio}")
        if movido > 0:
            movidas += 1
        if movido < det.cantidad_recibida:
            faltantes += 1
    return movidas, faltantes


def _traspasar_existencias(*, empresa, sucursal, producto, origen_ubic, destino_ubic,
                           cantidad, usuario, referencia):
    """Mueve hasta `cantidad` unidades de un producto de una ubicación a otra,
    consumiendo las existencias disponibles y conservando lote/serie/propiedad.
    Devuelve cuántas unidades se movieron realmente."""
    restante = decimal.Decimal(cantidad)
    movido = decimal.Decimal('0')
    filas = Existencia.objects.filter(
        producto=producto, ubicacion=origen_ubic, cantidad__gt=0).select_related('lote', 'serie')
    for ex in filas:
        if restante <= 0:
            break
        q = min(ex.cantidad, restante)
        registrar_movimiento(
            empresa=empresa, sucursal=sucursal, producto=producto, ubicacion=origen_ubic,
            tipo='TRASPASO_SAL', origen='AJUSTE', cantidad=q, usuario=usuario,
            lote=ex.lote, serie=ex.serie, propiedad=ex.propiedad, consignante=ex.consignante,
            referencia=referencia)
        registrar_movimiento(
            empresa=empresa, sucursal=sucursal, producto=producto, ubicacion=destino_ubic,
            tipo='TRASPASO_ENT', origen='AJUSTE', cantidad=q, usuario=usuario,
            lote=ex.lote, serie=ex.serie, propiedad=ex.propiedad, consignante=ex.consignante,
            referencia=referencia)
        restante -= q
        movido += q
    return movido


@transaction.atomic
def traspaso_interno(*, empresa, sucursal, origen_ubic, destino_ubic, partidas, usuario,
                     referencia='TRASP-INT'):
    """Traspaso inmediato entre dos ubicaciones de la MISMA sucursal (puede ser
    de almacenes distintos). `partidas` = lista de (producto, cantidad). Mueve
    el stock al instante conservando lote/serie/propiedad. Lanza StockInsuficiente
    si alguna partida no alcanza (la transacción revierte todo)."""
    if origen_ubic.id == destino_ubic.id:
        raise ValueError("La ubicación de origen y destino no pueden ser la misma.")

    movido_total = decimal.Decimal('0')
    for producto, cantidad in partidas:
        cantidad = decimal.Decimal(cantidad or 0)
        if cantidad <= 0:
            continue
        movido = _traspasar_existencias(
            empresa=empresa, sucursal=sucursal, producto=producto,
            origen_ubic=origen_ubic, destino_ubic=destino_ubic,
            cantidad=cantidad, usuario=usuario, referencia=referencia)
        if movido < cantidad:
            raise StockInsuficiente(
                f"No hay suficiente {producto.nombre} en {origen_ubic.codigo}: "
                f"se pidieron {cantidad} y solo hay {movido} disponibles.")
        movido_total += movido

    if movido_total <= 0:
        raise ValueError("Agrega al menos una partida con cantidad mayor a 0.")
    return movido_total


# Tipos que suman stock; el resto resta
TIPOS_ENTRADA = {
    'ENTRADA', 'AJUSTE_POS', 'TRASPASO_ENT', 'KIT_RETORNO', 'PROD_ENTRADA',
    'CAJA_REAB_ENT',
}
TIPOS_SALIDA = {
    'SALIDA', 'AJUSTE_NEG', 'TRASPASO_SAL', 'KIT_SALIDA', 'KIT_CONSUMO',
    'PROD_CONSUMO', 'VENTA', 'CAJA_REAB_SAL',
}


class StockInsuficiente(Exception):
    pass


@transaction.atomic
def registrar_movimiento(*, empresa, sucursal, producto, ubicacion, tipo, origen,
                         cantidad, usuario, lote=None, serie=None,
                         referencia=None, costo_unitario=None, notas=None,
                         propiedad='PROPIO', consignante=None):
    """Registra un movimiento en el kardex y actualiza la existencia.

    - Para entradas: crea/incrementa la Existencia.
    - Para salidas: valida stock suficiente y decrementa.
    - Series: la cantidad siempre debe ser 1 por movimiento.
    Devuelve el MovimientoInventario creado.
    """
    cantidad = decimal.Decimal(cantidad)
    if cantidad <= 0:
        raise ValueError("La cantidad del movimiento debe ser mayor a cero.")

    if serie and cantidad != 1:
        raise ValueError("Los movimientos de productos serializados deben ser de cantidad 1.")

    if producto.es_loteable and not lote and tipo in TIPOS_ENTRADA | TIPOS_SALIDA:
        if not serie:  # un producto puede ser loteable o serializable, no forzamos ambos
            raise ValueError(f"El producto {producto.sku} requiere lote.")

    if producto.es_serializable and not serie:
        raise ValueError(f"El producto {producto.sku} requiere número de serie.")

    almacen = ubicacion.almacen

    if tipo in TIPOS_ENTRADA:
        existencia, _ = Existencia.objects.select_for_update().get_or_create(
            producto=producto, sucursal=sucursal, almacen=almacen,
            ubicacion=ubicacion, lote=lote, serie=serie,
            propiedad=propiedad, consignante=consignante,
        )
        existencia.cantidad += cantidad
        existencia.save()
    elif tipo in TIPOS_SALIDA:
        existencia = Existencia.objects.select_for_update().filter(
            producto=producto, ubicacion=ubicacion, lote=lote, serie=serie,
            propiedad=propiedad, consignante=consignante,
        ).first()
        disponible = existencia.cantidad if existencia else decimal.Decimal('0')
        if disponible < cantidad:
            detalle = f" (lote {lote.numero_lote})" if lote else (f" (serie {serie.serie})" if serie else "")
            raise StockInsuficiente(
                f"Stock insuficiente de {producto.sku}{detalle} en {ubicacion}: "
                f"disponible {disponible}, solicitado {cantidad}."
            )
        existencia.cantidad -= cantidad
        existencia.save()
    else:
        raise ValueError(f"Tipo de movimiento desconocido: {tipo}")

    return MovimientoInventario.objects.create(
        empresa=empresa, sucursal=sucursal, producto=producto,
        almacen=almacen, ubicacion=ubicacion, lote=lote, serie=serie,
        propiedad=propiedad, consignante=consignante,
        tipo=tipo, origen=origen, referencia=referencia,
        cantidad=cantidad,
        costo_unitario=costo_unitario if costo_unitario is not None else producto.costo_unitario,
        usuario=usuario, notas=notas,
    )


@transaction.atomic
def registrar_retorno_kit(*, salida, retornos, usuario, cobrados=None):
    """Procesa el regreso de una salida de kit.

    Por cada línea se manejan dos cifras independientes:
      - retornada (dict `retornos`): lo que regresó al stock (movimiento KIT_RETORNO).
      - cobrada/consumo (dict `cobrados`): lo que realmente se cobra (= cantidad_post
        del sistema viejo). Si no se especifica, default = enviada − retornada.
    La diferencia (enviada − retornada − cobrada) es merma / servicio no cobrado.
    Reutilizable por inventarios (Kits) y cirugías.
    """
    from django.utils import timezone
    cobrados = cobrados or {}
    empresa = salida.empresa
    sucursal = salida.sucursal_origen

    def _get(d, key, default):
        if key in d: return d[key]
        if str(key) in d: return d[str(key)]
        return default

    for item in salida.contenido.select_related('producto', 'lote', 'serie', 'ubicacion_origen'):
        retornada = decimal.Decimal(_get(retornos, item.id, 0) or 0)
        if retornada < 0 or retornada > item.cantidad_enviada:
            raise ValueError(
                f"Cantidad retornada inválida para {item.producto.nombre}: "
                f"debe estar entre 0 y {item.cantidad_enviada}.")

        cob_raw = _get(cobrados, item.id, None)
        if cob_raw in (None, ''):
            usada = item.cantidad_enviada - retornada
        else:
            usada = decimal.Decimal(cob_raw or 0)
        max_cobrable = item.cantidad_enviada - retornada
        if usada < 0 or usada > max_cobrable:
            raise ValueError(
                f"Cantidad a cobrar inválida para {item.producto.nombre}: "
                f"debe estar entre 0 y {max_cobrable} (enviada − regresada).")

        if retornada > 0:
            registrar_movimiento(
                empresa=empresa, sucursal=sucursal, producto=item.producto,
                ubicacion=item.ubicacion_origen, tipo='KIT_RETORNO', origen='KIT',
                cantidad=retornada, usuario=usuario,
                lote=item.lote, serie=item.serie, referencia=salida.folio,
                propiedad=item.propiedad, consignante=item.consignante,
            )
            if item.serie:
                item.serie.estado = 'DISPONIBLE'
                item.serie.save()
        if usada > 0 and item.serie:
            item.serie.estado = 'VENDIDA'
            item.serie.save()

        item.cantidad_retornada = retornada
        item.cantidad_usada = usada
        item.save()

    salida.estado = 'RETORNADA'
    salida.fecha_retorno_real = timezone.now()
    salida.retorno_procesado_por = usuario
    salida.save()
    salida.instancia_kit.estado = 'RETORNADA'
    salida.instancia_kit.save()


def ubicacion_de_caja(caja):
    """Devuelve (creando si hace falta) la ubicación de stock de una caja.
    Las cajas viven en un almacén 'CAJAS' por sucursal."""
    from .models import Almacen, Ubicacion
    if caja.ubicacion_id:
        return caja.ubicacion
    empresa = caja.empresa_efectiva
    almacen, _ = Almacen.objects.get_or_create(
        empresa=empresa, sucursal=caja.sucursal_actual, codigo='CAJAS',
        defaults={'nombre': 'Cajas / Kits'})
    ubic, _ = Ubicacion.objects.get_or_create(
        almacen=almacen, codigo=caja.codigo_caja[:20],
        defaults={'descripcion': f'Caja {caja.codigo_caja}'})
    caja.ubicacion = ubic
    caja.save(update_fields=['ubicacion'])
    return ubic


@transaction.atomic
def reabastecer_caja(*, caja, origen_ubicacion, cantidades, usuario):
    """Mueve piezas del almacén (origen_ubicacion) a la caja hasta dejarla lista.
    cantidades: dict {producto_id: cantidad_a_agregar}.
    """
    from .models import Producto
    destino = ubicacion_de_caja(caja)
    empresa = caja.empresa_efectiva
    sucursal = caja.sucursal_actual
    movidas = 0
    for pid, qty in cantidades.items():
        q = decimal.Decimal(qty or 0)
        if q <= 0:
            continue
        prod = Producto.objects.get(id=pid, empresa=empresa)
        # Salida del almacén origen (valida stock) y entrada a la caja
        registrar_movimiento(
            empresa=empresa, sucursal=sucursal, producto=prod, ubicacion=origen_ubicacion,
            tipo='CAJA_REAB_SAL', origen='KIT', cantidad=q, usuario=usuario,
            referencia=f'REAB {caja.codigo_caja}')
        registrar_movimiento(
            empresa=empresa, sucursal=sucursal, producto=prod, ubicacion=destino,
            tipo='CAJA_REAB_ENT', origen='KIT', cantidad=q, usuario=usuario,
            referencia=f'REAB {caja.codigo_caja}',
            propiedad=caja.propiedad, consignante=caja.consignante)
        movidas += 1
    return movidas


@transaction.atomic
def vaciar_caja(*, caja, destino_ubicacion, usuario):
    """Regresa TODO el contenido físico de la caja al almacén (destino_ubicacion).
    Conserva lote/serie/propiedad/consignante de cada existencia.
    Devuelve cuántas líneas se movieron."""
    origen = ubicacion_de_caja(caja)
    empresa = caja.empresa_efectiva
    sucursal = caja.sucursal_actual
    movidas = 0
    existencias = list(Existencia.objects.filter(ubicacion=origen, cantidad__gt=0).select_related(
        'producto', 'lote', 'serie'))
    for ex in existencias:
        registrar_movimiento(
            empresa=empresa, sucursal=sucursal, producto=ex.producto, ubicacion=origen,
            tipo='CAJA_REAB_SAL', origen='KIT', cantidad=ex.cantidad, usuario=usuario,
            lote=ex.lote, serie=ex.serie, referencia=f'VACIA {caja.codigo_caja}',
            propiedad=ex.propiedad, consignante=ex.consignante)
        registrar_movimiento(
            empresa=empresa, sucursal=sucursal, producto=ex.producto, ubicacion=destino_ubicacion,
            tipo='CAJA_REAB_ENT', origen='KIT', cantidad=ex.cantidad, usuario=usuario,
            lote=ex.lote, serie=ex.serie, referencia=f'VACIA {caja.codigo_caja}',
            propiedad=ex.propiedad, consignante=ex.consignante)
        movidas += 1
    return movidas


@transaction.atomic
def armar_caja(*, caja, lineas, origen_ubicacion, usuario, mover_stock=True):
    """Llenado libre de una caja: fija su receta (ContenidoCaja) y, opcionalmente,
    mete el stock físico en un solo paso.

    lineas: iterable de dicts {producto_id, cantidad, es_retornable}.
    - Para cajas PROPIO: mueve `cantidad` del `origen_ubicacion` al contenedor.
    - El stock movido hereda la propiedad/consignante de la caja.
    Devuelve cuántas líneas se procesaron.
    """
    from .models import Producto, ContenidoCaja
    destino = ubicacion_de_caja(caja)
    empresa = caja.empresa_efectiva
    sucursal = caja.sucursal_actual
    procesadas = 0
    for ln in lineas:
        pid = ln.get('producto_id')
        q = decimal.Decimal(ln.get('cantidad') or 0)
        if not pid or q <= 0:
            continue
        prod = Producto.objects.get(id=pid, empresa=empresa)
        ContenidoCaja.objects.update_or_create(
            caja=caja, producto=prod,
            defaults={'cantidad_objetivo': q, 'es_retornable': bool(ln.get('es_retornable'))})
        if mover_stock and origen_ubicacion is not None:
            registrar_movimiento(
                empresa=empresa, sucursal=sucursal, producto=prod, ubicacion=origen_ubicacion,
                tipo='CAJA_REAB_SAL', origen='KIT', cantidad=q, usuario=usuario,
                referencia=f'ARMA {caja.codigo_caja}')
            registrar_movimiento(
                empresa=empresa, sucursal=sucursal, producto=prod, ubicacion=destino,
                tipo='CAJA_REAB_ENT', origen='KIT', cantidad=q, usuario=usuario,
                referencia=f'ARMA {caja.codigo_caja}',
                propiedad=caja.propiedad, consignante=caja.consignante)
        procesadas += 1
    return procesadas


@transaction.atomic
def enviar_caja_a_cirugia(*, salida, usuario):
    """La caja sale a la cirugía con TODO su contenido actual (lo que trae).
    Baja ese stock de la ubicación de la caja y lo registra como contenido del viaje.
    """
    from django.utils import timezone
    from .models import ContenidoSalidaKit, Existencia
    caja = salida.instancia_kit
    ubic = ubicacion_de_caja(caja)
    retornables = {prod.id: ret for (prod, _cant, ret) in caja.lineas_objetivo()}

    hubo = False
    existencias = list(Existencia.objects.filter(ubicacion=ubic, cantidad__gt=0).select_related('producto', 'lote', 'serie'))
    for ex in existencias:
        registrar_movimiento(
            empresa=salida.empresa, sucursal=salida.sucursal_origen, producto=ex.producto,
            ubicacion=ubic, tipo='KIT_SALIDA', origen='KIT', cantidad=ex.cantidad,
            usuario=usuario, lote=ex.lote, serie=ex.serie, referencia=salida.folio,
            propiedad=ex.propiedad, consignante=ex.consignante)
        if ex.serie:
            ex.serie.estado = 'EN_KIT'; ex.serie.save(update_fields=['estado'])
        ContenidoSalidaKit.objects.create(
            salida=salida, producto=ex.producto, lote=ex.lote, serie=ex.serie,
            ubicacion_origen=ubic, es_retornable=retornables.get(ex.producto_id, False),
            propiedad=ex.propiedad, consignante=ex.consignante, cantidad_enviada=ex.cantidad)
        hubo = True

    if not hubo:
        raise ValueError("La caja está vacía. Reabastécela antes de surtir.")

    salida.estado = 'ENVIADA'
    salida.fecha_salida = timezone.now()
    salida.save()
    caja.estado = 'EN_CAMPO'
    caja.save(update_fields=['estado'])


def stock_disponible(producto, ubicacion=None, sucursal=None, lote=None, serie=None):
    """Suma la existencia disponible con los filtros dados."""
    qs = Existencia.objects.filter(producto=producto)
    if ubicacion:
        qs = qs.filter(ubicacion=ubicacion)
    if sucursal:
        qs = qs.filter(sucursal=sucursal)
    if lote:
        qs = qs.filter(lote=lote)
    if serie:
        qs = qs.filter(serie=serie)
    from django.db.models import Sum
    return qs.aggregate(total=Sum('cantidad'))['total'] or decimal.Decimal('0')
