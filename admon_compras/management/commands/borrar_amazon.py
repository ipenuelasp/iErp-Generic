"""Borra TODO lo que cargó el importador de Amazon, para recargar limpio.

Alcance (por empresa): órdenes de compra con folio `AMZ-OC-*` y, ligado a ellas,
sus recepciones, CxP, egresos, movimientos de inventario y los productos creados
(con su existencia). NO toca nada que no sea de Amazon (FDC, GPE, SACS, INM, renta).

Salvaguardas:
- Un producto NO se borra si ya se usó en una venta (pedido/cotización) o en otra
  OC que no sea de Amazon; en ese caso solo se revierte su stock de Amazon y se
  reporta para que lo revises.
- Corre primero con --dry-run para ver exactamente qué se borraría.

Uso:
    python manage.py borrar_amazon --empresa <id> [--dry-run]
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum, Q


class Command(BaseCommand):
    help = "Elimina las cargas de Amazon (OC AMZ-OC-*) y sus productos/existencias."

    def add_arguments(self, parser):
        parser.add_argument('--empresa', type=int, required=True)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        from admon_empresas.models import Empresa
        from admon_compras.models import OrdenCompra, DetalleOrdenCompra, Proveedor
        from admon_inventarios.models import (
            RecepcionMaterial, DetalleRecepcion, MovimientoInventario, Existencia, Producto)
        from admon_finanzas.models import FacturaProveedor
        from admon_ventas.models import DetallePedido, DetalleCotizacion

        try:
            empresa = Empresa.objects.get(pk=opts['empresa'])
        except Empresa.DoesNotExist:
            raise CommandError(f"No existe empresa con id {opts['empresa']}.")
        dry = opts['dry_run']

        ocs = OrdenCompra.objects.filter(empresa=empresa, folio__startswith='AMZ-OC-')
        oc_ids = list(ocs.values_list('id', flat=True))
        folios = list(ocs.values_list('folio', flat=True))
        prod_ids = set(DetalleOrdenCompra.objects.filter(
            orden_id__in=oc_ids).values_list('producto_id', flat=True))

        receps = RecepcionMaterial.objects.filter(orden_compra_id__in=oc_ids)
        facturas = FacturaProveedor.objects.filter(orden_compra_id__in=oc_ids)
        # Movimientos ligados a esas OC (import, cancelaciones y dedups)
        mov_q = Q(empresa=empresa) & (Q(referencia__in=folios) |
                                      Q(referencia__contains='AMZ-OC-'))
        movs = MovimientoInventario.objects.filter(mov_q)

        # Clasificar productos: vendidos / compartidos NO se borran
        vendidos = set(DetallePedido.objects.filter(
            producto_id__in=prod_ids).values_list('producto_id', flat=True))
        vendidos |= set(DetalleCotizacion.objects.filter(
            producto_id__in=prod_ids).values_list('producto_id', flat=True))
        compartidos = set(DetalleOrdenCompra.objects.filter(
            producto_id__in=prod_ids).exclude(orden_id__in=oc_ids
            ).values_list('producto_id', flat=True))
        no_borrables = vendidos | compartidos
        borrables = prod_ids - no_borrables

        self.stdout.write(self.style.WARNING(
            f"\n{'(DRY-RUN) ' if dry else ''}Empresa {empresa.nombre_fiscal} — alcance Amazon:"))
        self.stdout.write(f"  Órdenes de compra : {len(oc_ids)}")
        self.stdout.write(f"  Recepciones       : {receps.count()}")
        self.stdout.write(f"  CxP (facturas)    : {facturas.count()}")
        self.stdout.write(f"  Movimientos inv.  : {movs.count()}")
        self.stdout.write(f"  Productos ligados : {len(prod_ids)}")
        self.stdout.write(f"     · a eliminar   : {len(borrables)}")
        self.stdout.write(f"     · a conservar  : {len(no_borrables)} (vendidos/compartidos)")
        if no_borrables:
            for p in Producto.objects.filter(id__in=no_borrables):
                motivo = 'vendido' if p.id in vendidos else 'en otra OC'
                self.stdout.write(self.style.NOTICE(f"        - {p.sku} {p.nombre[:40]} ({motivo})"))

        if dry:
            self.stdout.write(self.style.SUCCESS("\nDry-run: no se borró nada."))
            return

        with transaction.atomic():
            # 1) CxP + egresos
            for fp in facturas:
                for ap in fp.aplicaciones.all():
                    pago = ap.pago
                    ap.delete()
                    if pago and not pago.aplicaciones.exists():
                        pago.delete()
            facturas.delete()

            # 2) Recepciones
            DetalleRecepcion.objects.filter(recepcion__in=receps).delete()
            receps.delete()

            # 3) Movimientos ligados a las OC de Amazon
            movs.delete()

            # 4) Detalle de OC + OC
            DetalleOrdenCompra.objects.filter(orden_id__in=oc_ids).delete()
            ocs.delete()

            # 5) Productos eliminables: borrar sus movimientos/existencia restantes y el producto
            borrados = 0
            for pid in borrables:
                sid = transaction.savepoint()
                try:
                    MovimientoInventario.objects.filter(producto_id=pid).delete()
                    DetalleRecepcion.objects.filter(producto_id=pid).delete()
                    DetalleOrdenCompra.objects.filter(producto_id=pid).delete()
                    Existencia.objects.filter(producto_id=pid).delete()
                    Producto.objects.filter(id=pid).delete()  # cascada lote/serie/config
                    transaction.savepoint_commit(sid)
                    borrados += 1
                except Exception as e:
                    transaction.savepoint_rollback(sid)
                    self.stdout.write(self.style.ERROR(
                        f"  No se pudo borrar producto id {pid}: {e}"))

            # 6) Recalcular existencia de los productos conservados (quitar stock Amazon)
            from admon_inventarios.services import TIPOS_ENTRADA, TIPOS_SALIDA
            for pid in no_borrables:
                for ex in Existencia.objects.filter(producto_id=pid):
                    real = MovimientoInventario.objects.filter(
                        producto_id=pid, ubicacion=ex.ubicacion, lote=ex.lote, serie=ex.serie
                    ).aggregate(
                        e=Sum('cantidad', filter=Q(tipo__in=TIPOS_ENTRADA)),
                        s=Sum('cantidad', filter=Q(tipo__in=TIPOS_SALIDA)))
                    ex.cantidad = (real['e'] or 0) - (real['s'] or 0)
                    ex.save(update_fields=['cantidad'])

            # 7) Proveedor Amazon si quedó sin documentos
            amz = Proveedor.objects.filter(empresa=empresa, nombre_comercial='Amazon').first()
            if amz and not OrdenCompra.objects.filter(proveedor=amz).exists() \
                    and not FacturaProveedor.objects.filter(proveedor=amz).exists():
                amz.delete()

        self.stdout.write(self.style.SUCCESS(
            f"\nListo. Productos eliminados: {borrados}. "
            f"Conservados (revisa stock): {len(no_borrables)}."))
