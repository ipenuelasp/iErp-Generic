"""Importador del export de pedidos de Amazon Business (CSV).

Por cada orden de Amazon genera el rastro de compra completo:
  Orden de Compra (FINALIZADA) → Recepción (stock al costo)
  → Factura de proveedor (CxP) → Egreso (pagado).
Crea/actualiza 1 producto por ASIN. Respeta la fecha real del pedido.
Idempotente: si la OC de una orden ya existe (folio AMZ-OC-<orden>), se omite.
"""
import csv
import io
import decimal
from datetime import datetime

from django.db import transaction
from django.utils import timezone

D0 = decimal.Decimal('0')
CENT = decimal.Decimal('0.01')


def _fecha(s):
    """Fecha del pedido (dd/mm/aaaa) → datetime aware (mediodía)."""
    s = (s or '').strip()
    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%m/%d/%Y'):
        try:
            dt = datetime.strptime(s, fmt).replace(hour=12)
            return timezone.make_aware(dt) if timezone.is_naive(dt) else dt
        except ValueError:
            continue
    return None


def _num(s):
    if s is None:
        return D0
    s = str(s).replace('=', '').replace('"', '').replace(',', '').strip()
    try:
        return decimal.Decimal(s or '0')
    except Exception:
        return D0


def _tasa(s):
    """'16%' -> 16, '0%' -> 0, '' -> 0."""
    s = (s or '').replace('%', '').strip()
    try:
        return int(float(s))
    except ValueError:
        return 0


def _grupo_codigo(titulo, categoria):
    t = (titulo or '').lower()
    if any(k in t for k in ['laptop', 'notebook', 'portátil', 'portatil']):
        return 'LAPTOP'
    if 'monitor' in t or 'pantalla' in t:
        return 'MONITOR'
    if any(k in t for k in ['mini pc', 'minipc', 'desktop', 'computadora de escritorio',
                            'all-in-one', 'workstation']):
        return 'COMPUTO'
    cat = (categoria or '').lower()
    tech = ['personal computer', 'ce', 'wireless', 'speaker', 'office', 'photography',
            'car audio', 'business', 'industrial', 'computer']
    if any(x in cat for x in tech):
        return 'PERIF'
    return 'OTROS'


@transaction.atomic
def importar(archivo, empresa, sucursal, usuario):
    """Procesa el CSV de Amazon (flujo completo de compra). Devuelve resumen."""
    from admon_inventarios.models import (Producto, Grupo, UnidadMedida, Almacen,
                                          Ubicacion, RecepcionMaterial, DetalleRecepcion,
                                          MovimientoInventario)
    from admon_inventarios.services import registrar_movimiento
    from admon_empresas.models import Impuesto, Moneda
    from admon_compras.models import Proveedor, OrdenCompra, DetalleOrdenCompra
    from admon_finanzas.models import FacturaProveedor, Pago, AplicacionPago

    alm = Almacen.objects.filter(empresa=empresa, sucursal=sucursal).exclude(codigo='CAJAS').first()
    ubic = Ubicacion.objects.filter(almacen=alm).first() if alm else None
    if not ubic:
        raise ValueError("La sucursal no tiene un almacén con ubicación. Crea uno en Configuración antes de importar.")

    moneda = empresa.moneda_principal or Moneda.objects.filter(empresa=empresa).first()
    if not moneda:
        raise ValueError("La empresa no tiene moneda. Agrega una en Configuración.")

    pza = UnidadMedida.objects.filter(empresa=empresa, codigo='PZA').first()
    iva_def = Impuesto.objects.filter(empresa=empresa, es_default=True).first()
    imps = {int(i.tasa): i for i in Impuesto.objects.filter(empresa=empresa, es_retencion=False)}
    grupos = {g.codigo: g for g in Grupo.objects.filter(empresa=empresa)}

    proveedor, _ = Proveedor.objects.get_or_create(
        empresa=empresa, nombre_comercial='Amazon',
        defaults=dict(nombre_fiscal='Amazon (marketplace)', rfc='XAXX010101000',
                      moneda_predeterminada=moneda, dias_credito=0, activo=True))

    def grupo_de(titulo, categoria):
        code = _grupo_codigo(titulo, categoria)
        g = grupos.get(code)
        if not g and code == 'OTROS':
            g = Grupo.objects.create(empresa=empresa, codigo='OTROS', descripcion='Otros', es_inventariable=True)
            grupos['OTROS'] = g
        return g or grupos.get('PERIF')

    data = archivo.read().decode('utf-8-sig', errors='replace')
    reader = csv.DictReader(io.StringIO(data))

    ordenes = {}
    for row in reader:
        if (row.get('Estatus del pedido') or '').strip().lower() == 'cancelado':
            continue
        oid = (row.get('Identificador de pedido') or '').strip()
        if not (row.get('ASIN') or '').strip():
            continue
        ordenes.setdefault(oid, []).append(row)

    # El export de Amazon a veces repite la MISMA línea (mismo pedido, ASIN,
    # cantidad y precio): es un artefacto del CSV, no una compra real. Se colapsa
    # a una sola para no duplicar stock ni la CxP.
    for oid, filas in ordenes.items():
        vistos = set()
        unicas = []
        for r in filas:
            clave = (r.get('ASIN', '').strip(),
                     (r.get('Cantidad de producto') or '').strip(),
                     (r.get('PPU de la compra') or '').strip(),
                     (r.get('Título') or '').strip())
            if clave in vistos:
                continue
            vistos.add(clave)
            unicas.append(r)
        ordenes[oid] = unicas

    last = OrdenCompra.objects.filter(empresa=empresa).order_by('consecutivo').last()
    consec = last.consecutivo if last else 0

    res = dict(prod_creados=0, prod_actualizados=0, ordenes=0, recepciones=0,
               omitidas=0, lineas=0, gasto=D0)

    for oid, filas in ordenes.items():
        folio_oc = f"AMZ-OC-{oid}"
        if OrdenCompra.objects.filter(empresa=empresa, folio=folio_oc).exists():
            res['omitidas'] += 1
            continue

        # Órdenes a $0 (reposiciones/garantías) no entran a inventario ni a CxP.
        total_orden = sum((_num(r.get('PPU de la compra')) * (_num(r.get('Cantidad de producto')) or decimal.Decimal('1'))
                           for r in filas), D0)
        if total_orden <= 0:
            res['omitidas'] += 1
            continue

        fecha_dt = _fecha(filas[0].get('Fecha del pedido'))
        fdate = fecha_dt.date() if fecha_dt else timezone.now().date()
        consec += 1

        oc = OrdenCompra.objects.create(
            empresa=empresa, sucursal_destino=sucursal, proveedor=proveedor, moneda=moneda,
            folio=folio_oc, consecutivo=consec, estado='FINALIZADO', creado_por=usuario,
            notas=f"Amazon · orden {oid}")
        rec = RecepcionMaterial.objects.create(
            empresa=empresa, sucursal=sucursal, orden_compra=oc, proveedor_nombre='Amazon',
            numero_factura=f"AMZ-{oid}", recibido_por=usuario, notas=f"Amazon · orden {oid}")

        sub = D0
        imp = D0
        mov_ids = []
        for row in filas:
            asin = row['ASIN'].strip()
            titulo = (row.get('Título') or '').strip()[:255]
            cant = _num(row.get('Cantidad de producto')) or decimal.Decimal('1')
            tasa = _tasa(row.get('Tipo de IVA del subtotal del producto'))
            grupo = grupo_de(titulo, row.get('Categoría de producto interna de Amazon'))

            # Costo real: usar el "Total neto del producto" (lo que de verdad se
            # pagó, ya con promociones/descuentos) y de ahí derivar el costo sin
            # IVA. Si no viene, usar PPU de la compra (precio de lista).
            factor = decimal.Decimal(1) + decimal.Decimal(tasa) / 100
            net_line = _num(row.get('Total neto del producto'))
            ppu = _num(row.get('PPU de la compra'))
            if net_line > 0 and factor > 0:
                sub_line = (net_line / factor)
                costo = (sub_line / cant) if cant else ppu
            else:
                costo = ppu
                sub_line = cant * costo
            costo = costo.quantize(decimal.Decimal('0.0001'))

            prod, creado = Producto.objects.get_or_create(
                empresa=empresa, sku=asin,
                defaults=dict(
                    nombre=titulo or asin, costo_unitario=costo, precio_venta=costo,
                    grupo=grupo, unidad_medida=pza, impuesto=imps.get(tasa) or iva_def,
                    codigo_barras=(row.get('Número de modelo del artículo') or '').replace('=', '').replace('"', '')[:50] or None,
                    alcance='GLOBAL', es_comprable=True, es_vendible=True, activo=True))
            if creado:
                res['prod_creados'] += 1
            else:
                if costo > 0 and prod.costo_unitario != costo:
                    prod.costo_unitario = costo
                    prod.save(update_fields=['costo_unitario'])
                res['prod_actualizados'] += 1

            if cant <= 0:
                continue
            d_oc = DetalleOrdenCompra.objects.create(
                orden=oc, producto=prod, cantidad_pedida=cant, cantidad_recibida=cant,
                precio_unitario=costo, impuesto=imps.get(tasa) or iva_def, iva_porcentaje=tasa)
            DetalleRecepcion.objects.create(
                recepcion=rec, producto=prod, cantidad_recibida=cant, ubicacion=ubic,
                costo_unitario=costo, detalle_oc=d_oc)
            mov = registrar_movimiento(
                empresa=empresa, sucursal=sucursal, producto=prod, ubicacion=ubic,
                tipo='ENTRADA', origen='OC', cantidad=cant, usuario=usuario,
                costo_unitario=costo, referencia=oc.folio, notas='Import Amazon')
            mov_ids.append(mov.pk)
            linea_sub = (cant * costo)
            sub += linea_sub
            imp += linea_sub * decimal.Decimal(tasa) / 100
            res['lineas'] += 1

        oc.subtotal = sub.quantize(CENT)
        oc.impuestos = imp.quantize(CENT)
        oc.total = oc.subtotal + oc.impuestos
        oc.save()

        # Fechas reales (campos auto_now_add se fijan con update)
        OrdenCompra.objects.filter(pk=oc.pk).update(fecha_emision=fdate)
        RecepcionMaterial.objects.filter(pk=rec.pk).update(fecha_recepcion=fecha_dt or timezone.now())
        if mov_ids and fecha_dt:
            MovimientoInventario.objects.filter(pk__in=mov_ids).update(fecha=fecha_dt)

        # Factura de proveedor (CxP) + egreso pagado (a Amazon le pagas al momento)
        fp = FacturaProveedor.objects.create(
            empresa=empresa, orden_compra=oc, proveedor=proveedor, folio=f"AMZ-{oid}",
            fecha_emision=fdate, moneda=moneda, subtotal=oc.subtotal, impuestos=oc.impuestos,
            total=oc.total, registrada_por=usuario, notas=f"Amazon · orden {oid}")
        pago = Pago.objects.create(
            empresa=empresa, tipo='EGRESO', proveedor=proveedor, fecha=fdate, moneda=moneda,
            monto=fp.total, creado_por=usuario, referencia=f"Amazon {oid}")
        AplicacionPago.objects.create(pago=pago, factura=fp, monto_aplicado=fp.total, tipo_cambio=1)
        fp.recalcular_estado()

        res['ordenes'] += 1
        res['recepciones'] += 1
        res['gasto'] += fp.total

    return res


def _costo_real(row):
    """Costo unitario sin IVA, usando el 'Total neto del producto' (monto real
    pagado, con promociones). Si no viene, usa el PPU de la compra."""
    cant = _num(row.get('Cantidad de producto')) or decimal.Decimal('1')
    tasa = _tasa(row.get('Tipo de IVA del subtotal del producto'))
    factor = decimal.Decimal(1) + decimal.Decimal(tasa) / 100
    net = _num(row.get('Total neto del producto'))
    ppu = _num(row.get('PPU de la compra'))
    if net > 0 and factor > 0 and cant:
        costo = net / factor / cant
    else:
        costo = ppu
    return costo.quantize(decimal.Decimal('0.0001')), tasa


@transaction.atomic
def recalcular_costos(archivo, empresa):
    """Re-lee el CSV de Amazon y corrige EN SU LUGAR el costo de las OC ya
    importadas (producto, detalle OC, recepción, movimientos, OC y CxP/egreso),
    usando el monto real (Total neto). No borra nada ni toca las ventas."""
    from admon_inventarios.models import Producto, MovimientoInventario, DetalleRecepcion
    from admon_compras.models import OrdenCompra, DetalleOrdenCompra
    from admon_finanzas.models import FacturaProveedor

    data = archivo.read().decode('utf-8-sig', errors='replace')
    reader = csv.DictReader(io.StringIO(data))

    # Agrupar por orden (dedup de filas idénticas)
    ordenes = {}
    for row in reader:
        if (row.get('Estatus del pedido') or '').strip().lower() == 'cancelado':
            continue
        if not (row.get('ASIN') or '').strip():
            continue
        ordenes.setdefault((row.get('Identificador de pedido') or '').strip(), []).append(row)

    res = dict(ordenes=0, lineas=0, no_encontradas=0, productos=0)
    for oid, filas in ordenes.items():
        oc = OrdenCompra.objects.filter(empresa=empresa, folio=f"AMZ-OC-{oid}").first()
        if not oc:
            res['no_encontradas'] += 1
            continue

        # Costo real por ASIN (colapsa duplicados quedándose con el último)
        costos = {}
        for row in filas:
            costo, tasa = _costo_real(row)
            costos[row['ASIN'].strip()] = costo

        for d in oc.detalles.select_related('producto'):
            sku = d.producto.sku
            if sku not in costos:
                continue
            costo = costos[sku]
            if d.precio_unitario != costo:
                d.precio_unitario = costo
                d.save(update_fields=['precio_unitario'])
            # Producto
            if d.producto.costo_unitario != costo:
                d.producto.costo_unitario = costo
                d.producto.save(update_fields=['costo_unitario'])
                res['productos'] += 1
            # Recepción
            DetalleRecepcion.objects.filter(detalle_oc=d).update(costo_unitario=costo)
            # Movimientos de entrada de esta OC para ese producto
            MovimientoInventario.objects.filter(
                empresa=empresa, referencia=oc.folio, producto=d.producto,
                tipo='ENTRADA').update(costo_unitario=costo)
            res['lineas'] += 1

        # Recalcular totales de la OC
        sub = D0
        imp = D0
        for d in oc.detalles.all():
            base = d.cantidad_pedida * d.precio_unitario
            sub += base
            imp += base * (d.iva_porcentaje or 0) / 100
        oc.subtotal = sub.quantize(CENT)
        oc.impuestos = imp.quantize(CENT)
        oc.total = oc.subtotal + oc.impuestos
        oc.save(update_fields=['subtotal', 'impuestos', 'total'])

        # CxP + egreso
        for fp in FacturaProveedor.objects.filter(orden_compra=oc):
            fp.subtotal = oc.subtotal
            fp.impuestos = oc.impuestos
            fp.total = oc.total
            fp.save(update_fields=['subtotal', 'impuestos', 'total'])
            for ap in fp.aplicaciones.all():
                ap.monto_aplicado = fp.total
                ap.save(update_fields=['monto_aplicado'])
                pago = ap.pago
                pago.monto = fp.total
                pago.save(update_fields=['monto'])
            if hasattr(fp, 'recalcular_estado'):
                fp.recalcular_estado()

        res['ordenes'] += 1
    return res
