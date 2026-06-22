"""Corrige las órdenes de compra de Amazon que se cargaron por duplicado.

El export CSV de Amazon a veces repite una misma línea (mismo pedido, ASIN,
cantidad y precio). El importador antiguo las sumaba, duplicando stock y la CxP.
Este comando detecta líneas idénticas dentro de cada OC `AMZ-OC-*`, elimina las
sobrantes, revierte el stock fantasma (AJUSTE_NEG) y recalcula OC, recepción,
CxP y egreso.

Uso:
    python manage.py corregir_duplicados_amazon --empresa <id> [--dry-run]
"""
import decimal
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

CENT = decimal.Decimal('0.01')


class Command(BaseCommand):
    help = "Revierte líneas duplicadas en las OC importadas de Amazon."

    def add_arguments(self, parser):
        parser.add_argument('--empresa', type=int, required=True,
                            help="ID de la empresa a corregir.")
        parser.add_argument('--dry-run', action='store_true',
                            help="Solo muestra qué haría, sin tocar la base.")

    def handle(self, *args, **opts):
        from admon_empresas.models import Empresa
        from admon_compras.models import OrdenCompra, DetalleOrdenCompra
        from admon_inventarios.models import DetalleRecepcion
        from admon_inventarios.services import registrar_movimiento, StockInsuficiente
        from admon_finanzas.models import FacturaProveedor

        try:
            empresa = Empresa.objects.get(pk=opts['empresa'])
        except Empresa.DoesNotExist:
            raise CommandError(f"No existe empresa con id {opts['empresa']}.")

        dry = opts['dry_run']
        ocs = OrdenCompra.objects.filter(
            empresa=empresa, folio__startswith='AMZ-OC-').exclude(estado='CANCELADO')

        total_ocs = 0
        total_lineas = 0
        total_unidades = decimal.Decimal('0')
        no_revertidas = 0

        for oc in ocs:
            grupos = defaultdict(list)
            for d in oc.detalles.all():
                grupos[(d.producto_id, d.cantidad_pedida, d.precio_unitario)].append(d)

            duplicados = [(k, v) for k, v in grupos.items() if len(v) > 1]
            if not duplicados:
                continue

            total_ocs += 1
            self.stdout.write(self.style.WARNING(f"\n{oc.folio} — {oc.proveedor}"))

            with transaction.atomic():
                for (prod_id, cant, precio), lineas in duplicados:
                    sobrantes = lineas[1:]  # se conserva la primera
                    for d in sobrantes:
                        rec_det = DetalleRecepcion.objects.filter(detalle_oc=d).first()
                        ubic = rec_det.ubicacion if rec_det else None
                        prod = d.producto
                        self.stdout.write(
                            f"   - {prod.sku} x{cant} @ {precio}  →  revertir")
                        if not dry:
                            if ubic:
                                try:
                                    registrar_movimiento(
                                        empresa=empresa, sucursal=oc.sucursal_destino,
                                        producto=prod, ubicacion=ubic,
                                        tipo='AJUSTE_NEG', origen='AJUSTE',
                                        cantidad=d.cantidad_pedida,
                                        usuario=oc.creado_por,
                                        referencia=f"DEDUP {oc.folio}",
                                        costo_unitario=d.precio_unitario,
                                        notas="Corrección duplicado Amazon")
                                except StockInsuficiente:
                                    no_revertidas += 1
                                    self.stdout.write(self.style.ERROR(
                                        f"     (ya se vendió, no se revirtió stock)"))
                            if rec_det:
                                rec_det.delete()
                            d.delete()
                        total_lineas += 1
                        total_unidades += cant

                if dry:
                    continue

                # Recalcular totales de la OC desde las líneas que quedaron
                sub = decimal.Decimal('0')
                imp = decimal.Decimal('0')
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

        resumen = (f"\n{'(DRY-RUN) ' if dry else ''}OCs corregidas: {total_ocs} · "
                   f"líneas duplicadas eliminadas: {total_lineas} · "
                   f"unidades revertidas: {total_unidades}")
        if no_revertidas:
            resumen += f" · {no_revertidas} sin revertir (ya vendidas)"
        self.stdout.write(self.style.SUCCESS(resumen))
