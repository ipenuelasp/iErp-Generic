"""Importador del export de pedidos de Amazon Business (CSV).

Crea/actualiza productos (1 por ASIN) y registra cada orden de Amazon como una
Recepción de material (entra stock al costo) bajo el proveedor 'Amazon'.
Idempotente: si una orden ya se importó (por su folio), se omite.
"""
import csv
import io
import decimal
from datetime import datetime

from django.db import transaction
from django.utils import timezone


def _fecha(s):
    """Convierte la fecha del pedido (dd/mm/aaaa) a datetime aware (mediodía)."""
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
        return decimal.Decimal('0')
    s = str(s).replace('=', '').replace('"', '').replace(',', '').strip()
    try:
        return decimal.Decimal(s or '0')
    except Exception:
        return decimal.Decimal('0')


def _grupo_codigo(titulo, categoria):
    """Heurística de clasificación a los grupos del cliente."""
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
    """Procesa el CSV de Amazon. Devuelve dict con el resumen."""
    from admon_inventarios.models import (Producto, Grupo, UnidadMedida, Almacen,
                                          Ubicacion, RecepcionMaterial, DetalleRecepcion,
                                          MovimientoInventario)
    from admon_inventarios.services import registrar_movimiento
    from admon_empresas.models import Impuesto

    # Destino de stock: primer almacén real de la sucursal
    alm = Almacen.objects.filter(empresa=empresa, sucursal=sucursal).exclude(codigo='CAJAS').first()
    ubic = Ubicacion.objects.filter(almacen=alm).first() if alm else None
    if not ubic:
        raise ValueError("La sucursal no tiene un almacén con ubicación. Crea uno en Configuración antes de importar.")

    pza = UnidadMedida.objects.filter(empresa=empresa, codigo='PZA').first()
    iva_def = Impuesto.objects.filter(empresa=empresa, es_default=True).first()
    grupos = {g.codigo: g for g in Grupo.objects.filter(empresa=empresa)}

    def grupo_de(titulo, categoria):
        code = _grupo_codigo(titulo, categoria)
        g = grupos.get(code)
        if not g and code == 'OTROS':
            g = Grupo.objects.create(empresa=empresa, codigo='OTROS', descripcion='Otros', es_inventariable=True)
            grupos['OTROS'] = g
        return g or grupos.get('PERIF')

    data = archivo.read().decode('utf-8-sig', errors='replace')
    reader = csv.DictReader(io.StringIO(data))

    # Agrupa filas por orden de Amazon
    ordenes = {}
    for row in reader:
        if (row.get('Estatus del pedido') or '').strip().lower() == 'cancelado':
            continue
        oid = (row.get('Identificador de pedido') or '').strip()
        if not (row.get('ASIN') or '').strip():
            continue
        ordenes.setdefault(oid, []).append(row)

    prod_creados = 0
    prod_actualizados = 0
    recepciones = 0
    omitidas = 0
    lineas = 0

    for oid, filas in ordenes.items():
        folio_ref = f"AMZ-{oid}"
        if RecepcionMaterial.objects.filter(empresa=empresa, numero_factura=folio_ref).exists():
            omitidas += 1
            continue

        fecha_dt = _fecha(filas[0].get('Fecha del pedido'))
        rec = RecepcionMaterial.objects.create(
            empresa=empresa, sucursal=sucursal, proveedor_nombre='Amazon',
            numero_factura=folio_ref, recibido_por=usuario,
            notas=f"Importación Amazon · orden {oid}")
        # fecha_recepcion es auto_now_add; se fija con update a la fecha real
        if fecha_dt:
            RecepcionMaterial.objects.filter(pk=rec.pk).update(fecha_recepcion=fecha_dt)
        mov_ids = []

        for row in filas:
            asin = row['ASIN'].strip()
            titulo = (row.get('Título') or '').strip()[:255]
            costo = _num(row.get('PPU de la compra'))
            cant = _num(row.get('Cantidad de producto')) or decimal.Decimal('1')
            grupo = grupo_de(titulo, row.get('Categoría de producto interna de Amazon'))

            prod, creado = Producto.objects.get_or_create(
                empresa=empresa, sku=asin,
                defaults=dict(
                    nombre=titulo or asin, costo_unitario=costo, precio_venta=costo,
                    grupo=grupo, unidad_medida=pza, impuesto=iva_def,
                    codigo_barras=(row.get('Número de modelo del artículo') or '').replace('=', '').replace('"', '')[:50] or None,
                    alcance='GLOBAL', es_comprable=True, es_vendible=True, activo=True))
            if creado:
                prod_creados += 1
            else:
                # Actualiza el último costo conocido
                if costo > 0 and prod.costo_unitario != costo:
                    prod.costo_unitario = costo
                    prod.save(update_fields=['costo_unitario'])
                prod_actualizados += 1

            if cant <= 0:
                continue
            DetalleRecepcion.objects.create(
                recepcion=rec, producto=prod, cantidad_recibida=cant,
                ubicacion=ubic, costo_unitario=costo)
            mov = registrar_movimiento(
                empresa=empresa, sucursal=sucursal, producto=prod, ubicacion=ubic,
                tipo='ENTRADA', origen='RECEPCION', cantidad=cant, usuario=usuario,
                costo_unitario=costo, referencia=folio_ref, notas='Import Amazon')
            mov_ids.append(mov.pk)
            lineas += 1

        # Fija la fecha real del pedido en los movimientos (kardex) de esta orden
        if fecha_dt and mov_ids:
            MovimientoInventario.objects.filter(pk__in=mov_ids).update(fecha=fecha_dt)
        recepciones += 1

    return {
        'prod_creados': prod_creados, 'prod_actualizados': prod_actualizados,
        'recepciones': recepciones, 'omitidas': omitidas, 'lineas': lineas,
    }
