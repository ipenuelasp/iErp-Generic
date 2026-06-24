"""
Motor de ventas: confirma la salida de inventario de un pedido, genera la
cuenta por cobrar en tesorería y dispara el reabastecimiento automático
desde la sucursal matriz cuando el stock cae bajo el mínimo.
"""
import decimal
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from admon_inventarios.models import (
    Existencia, Producto, ProductoSucursal, SolicitudTraspaso, DetalleTraspaso,
)
from admon_inventarios.services import registrar_movimiento, stock_disponible

from admon_empresas.models import Impuesto
from .models import Pedido, DetallePedido, ComisionPedido, Cotizacion


class ErrorVenta(Exception):
    pass


def recalcular_pedido(pedido):
    """Recalcula subtotal/impuestos/total del pedido desde sus partidas y
    actualiza la CxC ligada (si existe y no tiene cobros). Úsalo al agregar/
    quitar extras en el pedido."""
    subtotal = decimal.Decimal('0')
    imp_total = decimal.Decimal('0')
    for d in pedido.detalles.all():
        sub = d.cantidad * d.precio_unitario
        monto = sub * (d.iva_porcentaje / 100)
        subtotal += sub
        imp_total += (-monto if d.es_retencion else monto)
    pedido.subtotal = subtotal
    pedido.impuestos = imp_total
    pedido.total = subtotal + imp_total
    pedido.save(update_fields=['subtotal', 'impuestos', 'total'])

    # Sincronizar la CxC solo cuando hay UNA sola factura vigente y sin cobros
    # (pedido aún no entregado o con una sola entrega). Si el pedido tiene varias
    # facturas —una por entrega— cada una refleja su parcialidad y no se puede
    # repartir el extra automáticamente, así que no las tocamos.
    facturas = list(pedido.facturas.exclude(estado='CANCELADA')) if hasattr(pedido, 'facturas') else []
    if len(facturas) == 1 and facturas[0].total_pagado == 0:
        fac = facturas[0]
        fac.subtotal = subtotal
        fac.impuestos = imp_total
        fac.total = subtotal + imp_total
        fac.save(update_fields=['subtotal', 'impuestos', 'total'])
    return pedido


def _impuesto_para(producto, empresa, default_imp):
    imp = producto.impuesto or default_imp
    tasa = imp.tasa if imp else decimal.Decimal('0')
    es_ret = imp.es_retencion if imp else False
    return imp, tasa, es_ret


def _siguiente_folio_cxc(empresa):
    from admon_finanzas.models import FacturaCliente
    n = FacturaCliente.objects.filter(empresa=empresa).count() + 1
    return f"CXC-{n:05d}"


@transaction.atomic
def entregar_pedido(*, pedido, request):
    """Procesa la entrega (total o parcial) de un pedido.

    Lee, por cada partida, las existencias seleccionadas (ubicación/lote/serie)
    y sus cantidades: campos POST `ent_exist_<detalle_id>[]` y `ent_cant_<detalle_id>[]`.
    Descuenta inventario vía registrar_movimiento(VENTA), genera una factura de
    cliente (CxC) por lo entregado y reabastece si baja del mínimo.
    """
    empresa = pedido.empresa
    sucursal = pedido.sucursal

    if pedido.estado not in ('CONFIRMADO', 'ENTREGADO_PARCIAL'):
        raise ErrorVenta("El pedido debe estar confirmado para poder entregarse.")

    subtotal = decimal.Decimal('0')
    imp_total = decimal.Decimal('0')
    hubo_entrega = False
    productos_tocados = set()

    for det in pedido.detalles.select_related('producto', 'producto__grupo', 'impuesto'):
        # Servicios (renta, horas, proyectos): no mueven inventario; se entregan
        # automáticamente por lo pendiente y entran directo a la CxC.
        if det.producto.es_servicio:
            pend = det.pendiente_por_entregar
            # Cantidad a facturar de este servicio: la capturada (entrega parcial /
            # cobro por hitos) o, si no viene, todo lo pendiente. Nunca más de lo pendiente.
            cap = request.POST.get(f'ent_serv_{det.id}')
            if cap not in (None, ''):
                try:
                    entregado_det = decimal.Decimal(cap)
                except Exception:
                    entregado_det = decimal.Decimal('0')
            else:
                entregado_det = pend
            if entregado_det > pend:
                entregado_det = pend
            if entregado_det > 0:
                det.cantidad_entregada += entregado_det
                det.save(update_fields=['cantidad_entregada'])
                hubo_entrega = True
                sub = entregado_det * det.precio_unitario
                monto = sub * (det.iva_porcentaje / 100)
                subtotal += sub
                imp_total += (-monto if det.es_retencion else monto)
            continue

        exist_ids = request.POST.getlist(f'ent_exist_{det.id}[]')
        cants = request.POST.getlist(f'ent_cant_{det.id}[]')

        entregado_det = decimal.Decimal('0')
        for j, ex_id in enumerate(exist_ids):
            cant = decimal.Decimal(cants[j] or '0')
            if not ex_id or cant <= 0:
                continue
            existencia = Existencia.objects.select_related('lote', 'serie', 'ubicacion').filter(
                id=ex_id, producto=det.producto, sucursal=sucursal).first()
            if not existencia:
                raise ErrorVenta(f"Existencia inválida para {det.producto.sku}.")

            registrar_movimiento(
                empresa=empresa, sucursal=sucursal, producto=det.producto,
                ubicacion=existencia.ubicacion, tipo='VENTA', origen='VENTA',
                cantidad=cant, usuario=request.user,
                lote=existencia.lote, serie=existencia.serie,
                referencia=pedido.folio,
                notas=f"Venta a {pedido.cliente}",
            )
            if existencia.serie:
                existencia.serie.estado = 'VENDIDA'
                existencia.serie.save(update_fields=['estado'])

            entregado_det += cant
            productos_tocados.add(det.producto_id)

        if entregado_det <= 0:
            continue

        # No exceder lo pendiente
        if entregado_det > det.pendiente_por_entregar:
            raise ErrorVenta(
                f"Se intentó entregar {entregado_det} de {det.producto.sku}, "
                f"pero solo quedan {det.pendiente_por_entregar} pendientes.")

        det.cantidad_entregada += entregado_det
        det.save(update_fields=['cantidad_entregada'])
        hubo_entrega = True

        sub = entregado_det * det.precio_unitario
        monto = sub * (det.iva_porcentaje / 100)
        subtotal += sub
        imp_total += (-monto if det.es_retencion else monto)

    if not hubo_entrega:
        raise ErrorVenta("No se capturó ninguna cantidad a entregar.")

    # Estado del pedido
    pedido.estado = 'ENTREGADO' if pedido.esta_entregado_completo else 'ENTREGADO_PARCIAL'
    pedido.save(update_fields=['estado'])

    # Cuenta por cobrar por lo entregado
    factura = None
    if pedido.genera_cxc:
        factura = _crear_factura_cliente(pedido, request.user, subtotal, imp_total)

    # Reabastecimiento automático desde matriz
    reabastos = _reabastecer_si_bajo_minimo(empresa, sucursal, productos_tocados, request.user)

    return {'factura': factura, 'reabastos': reabastos}


@transaction.atomic
def liquidar_salida_kit(*, salida, cliente, moneda, comisiones, usuario):
    """Genera el pedido (ya entregado) que liquida una salida de kit/cirugía.

    - Consumibles usados → línea PRODUCTO (precio_venta, cantidad usada).
    - Retornables enviados → línea RENTA (precio_renta, cantidad enviada).
    El stock ya se movió en la salida/retorno del kit, así que aquí NO se
    vuelve a tocar inventario: solo se crea la venta + CxC y las comisiones.
    comisiones: lista de dicts {tipo, beneficiario, monto}.
    """
    if salida.estado != 'RETORNADA':
        raise ErrorVenta("La salida debe estar retornada (con el consumo capturado) para liquidarse.")
    if salida.pedido_generado_id:
        raise ErrorVenta("Esta salida ya fue liquidada.")
    if not cliente:
        raise ErrorVenta("Selecciona el cliente al que se le factura la cirugía.")

    empresa = salida.empresa
    sucursal = salida.sucursal_origen
    default_imp = Impuesto.objects.filter(empresa=empresa, es_default=True).first()

    ultimo = Pedido.objects.filter(empresa=empresa, sucursal=sucursal).order_by('consecutivo').last()
    consecutivo = (ultimo.consecutivo + 1) if ultimo else 1
    folio = f"{sucursal.codigo_sucursal or 'PED'}-CX-{consecutivo:05d}"

    pedido = Pedido.objects.create(
        empresa=empresa, sucursal=sucursal, cliente=cliente, moneda=moneda,
        folio=folio, consecutivo=consecutivo, estado='ENTREGADO', origen='CIRUGIA',
        genera_cxc=True, creado_por=usuario,
        notas=f"Liquidación de {salida.folio} · {salida.hospital_cliente}"
              + (f" · Dr. {salida.doctor_responsable}" if salida.doctor_responsable else ""),
    )

    subtotal = decimal.Decimal('0')
    imp_total = decimal.Decimal('0')

    for item in salida.contenido.select_related('producto'):
        prod = item.producto
        if item.es_retornable:
            cant = item.cantidad_enviada
            precio = prod.precio_renta
            tipo_linea = DetallePedido.LINEA_RENTA
        else:
            cant = item.cantidad_usada
            precio = prod.precio_venta
            tipo_linea = DetallePedido.LINEA_PRODUCTO
        if cant <= 0:
            continue

        imp, tasa, es_ret = _impuesto_para(prod, empresa, default_imp)
        sub = cant * precio
        monto = sub * (tasa / 100)
        DetallePedido.objects.create(
            pedido=pedido, producto=prod, tipo_linea=tipo_linea,
            cantidad=cant, cantidad_entregada=cant, precio_unitario=precio,
            impuesto=imp, iva_porcentaje=tasa, es_retencion=es_ret)
        subtotal += sub
        imp_total += (-monto if es_ret else monto)

    if not pedido.detalles.exists():
        transaction.set_rollback(True)
        raise ErrorVenta("La salida no tiene consumo ni renta por liquidar.")

    pedido.subtotal = subtotal
    pedido.impuestos = imp_total
    pedido.total = subtotal + imp_total
    pedido.save()

    for c in (comisiones or []):
        monto = decimal.Decimal(c.get('monto') or '0')
        if monto <= 0 or not c.get('beneficiario'):
            continue
        ComisionPedido.objects.create(
            pedido=pedido, tipo=c.get('tipo', 'TECNICO'),
            beneficiario=c['beneficiario'], monto=monto, notas=c.get('notas'))

    factura = None
    if pedido.genera_cxc:
        factura = _crear_factura_cliente(pedido, usuario, subtotal, imp_total)

    salida.pedido_generado = pedido
    salida.estado = 'CERRADA'
    salida.save(update_fields=['pedido_generado', 'estado'])
    caja = salida.instancia_kit
    caja.estado = 'DISPONIBLE'
    caja.save(update_fields=['estado'])

    return {'pedido': pedido, 'factura': factura}


@transaction.atomic
def convertir_cotizacion(*, cotizacion, usuario):
    """Crea un Pedido (BORRADOR) copiando las partidas de una cotización."""
    if cotizacion.estado == 'CONVERTIDA' or cotizacion.pedido_generado_id:
        raise ErrorVenta("Esta cotización ya fue convertida en pedido.")

    empresa = cotizacion.empresa
    sucursal = cotizacion.sucursal
    ultimo = Pedido.objects.filter(empresa=empresa, sucursal=sucursal).order_by('consecutivo').last()
    consecutivo = (ultimo.consecutivo + 1) if ultimo else 1
    from datetime import datetime
    folio = f"{sucursal.codigo_sucursal or 'PED'}-V{datetime.now().strftime('%y')}-{consecutivo:05d}"

    pedido = Pedido.objects.create(
        empresa=empresa, sucursal=sucursal, cliente=cotizacion.cliente, moneda=cotizacion.moneda,
        folio=folio, consecutivo=consecutivo, estado='BORRADOR', origen='COTIZACION',
        genera_cxc=True, creado_por=usuario, notas=cotizacion.notas,
        subtotal=cotizacion.subtotal, impuestos=cotizacion.impuestos, total=cotizacion.total,
    )
    for d in cotizacion.detalles.all():
        DetallePedido.objects.create(
            pedido=pedido, producto=d.producto, tipo_linea=d.tipo_linea,
            cantidad=d.cantidad, precio_unitario=d.precio_unitario,
            impuesto=d.impuesto, iva_porcentaje=d.iva_porcentaje, es_retencion=d.es_retencion)

    cotizacion.estado = 'CONVERTIDA'
    cotizacion.pedido_generado = pedido
    cotizacion.save(update_fields=['estado', 'pedido_generado'])
    return pedido


def _crear_factura_cliente(pedido, usuario, subtotal, imp_total):
    from admon_finanzas.models import FacturaCliente
    dias = pedido.cliente.dias_credito or 0
    hoy = timezone.now().date()
    return FacturaCliente.objects.create(
        empresa=pedido.empresa, pedido=pedido, cliente=pedido.cliente,
        folio=_siguiente_folio_cxc(pedido.empresa),
        fecha_emision=hoy,
        fecha_vencimiento=(hoy + timedelta(days=dias)) if dias else None,
        moneda=pedido.moneda,
        subtotal=subtotal, impuestos=imp_total, total=subtotal + imp_total,
        registrada_por=usuario,
    )


def _reabastecer_si_bajo_minimo(empresa, sucursal, producto_ids, usuario):
    """Si una sucursal NO matriz quedó bajo el stock mínimo de un producto,
    crea una solicitud de traspaso desde la matriz para resurtir."""
    if sucursal.es_matriz:
        return []

    from admon_empresas.models import Sucursal
    matriz = Sucursal.objects.filter(empresa=empresa, es_matriz=True).first()
    if not matriz or matriz.id == sucursal.id:
        return []

    creadas = []
    for pid in producto_ids:
        cfg = ProductoSucursal.objects.filter(producto_id=pid, sucursal=sucursal).first()
        minimo = cfg.stock_minimo if cfg else decimal.Decimal('0')
        if minimo <= 0:
            continue

        actual = stock_disponible(Producto.objects.get(id=pid), sucursal=sucursal)
        if actual >= minimo:
            continue

        # Cantidad sugerida: llevar hasta el máximo si existe, si no al mínimo
        objetivo = (cfg.stock_maximo if cfg and cfg.stock_maximo else minimo)
        faltante = objetivo - actual
        if faltante <= 0:
            continue

        solicitud = SolicitudTraspaso.objects.create(
            empresa=empresa, sucursal_origen=matriz, sucursal_destino=sucursal,
            estado='SOLICITADO', solicitado_por=usuario,
            notas_solicitud="Reabastecimiento automático por venta (stock bajo mínimo).",
        )
        DetalleTraspaso.objects.create(
            solicitud=solicitud, producto_id=pid, cantidad_solicitada=faltante)
        creadas.append(solicitud)

    return creadas
