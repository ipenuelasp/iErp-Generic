"""Carga las ventas de PendientesFacturar (FDC/GPE/SACS/INM): ciclo completo
pedido -> entrega (salida de inventario) -> CxC -> cobro (para las pagadas).

El pedido refacturado de GPE (Lenovo Legion Pro 7i) se carga a FDC y queda
PENDIENTE de cobro. Las facturas (CFDI) las sube el usuario a mano.

Idempotente por folio de pedido (PEND-*). Corre primero con --dry-run.

Uso:  python manage.py cargar_ventas_pendientes --empresa <id> [--dry-run]
"""
import decimal
from datetime import datetime, date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum, Q
from django.utils import timezone

D = decimal.Decimal
CENT = D('0.01')

# Cada venta: (folio, codigo_cliente, fecha_pago|None, [(sku, cantidad, precio_sin_iva), ...])
VENTAS = [
    ('PEND-FDC', 'FDC', date(2026, 5, 29), [
        ('STARLINK-75FT', 1, '2833.448275862072'),
        ('B0F24385XD', 3, '3981.81034482759'),
        ('B0CTY9H3RM', 1, '14633.52844827588'),
        ('B0FW19P9DD', 3, '27453.86767241384'),
        ('B0F2MCQ8XQ', 1, '9374.224999999999'),
        ('B0BVGP8T8D', 1, '4512.66465517241'),
    ]),
    ('PEND-FDC-LEGION', 'FDC', None, [   # refacturada de GPE -> FDC, sin cobro
        ('B0G2T512W3', 1, '48521.96767241384'),
    ]),
    ('PEND-GPE', 'GPE', date(2026, 5, 23), [
        ('B09SFPJS27', 4, '158.2103448275867'),
        ('B0DS231PCF', 1, '269.5663793103446'),
        ('B0FW19P9DD', 2, '27453.86767241384'),
    ]),
    ('PEND-SACS', 'SACS', date(2026, 5, 21), [
        ('B0CTY9H3RM', 1, '14633.52844827588'),
    ]),
    ('PEND-INM', 'INM', date(2026, 6, 12), [
        ('B0CTY9H3RM', 1, '14633.52844827588'),
        ('B0FHJDFBGQ', 3, '13380.200431034453'),
    ]),
]

# Producto que NO vino de Amazon (se compró en Mercado Libre): se crea + stock.
STARLINK = dict(sku='STARLINK-75FT', costo='2575.862068965517',
                nombre='Cable De Reemplazo Starlink 75ft 23m Cat 5e Exterior (Mercado Libre)')


class Command(BaseCommand):
    help = "Carga las ventas pendientes (FDC/GPE/SACS/INM) con su CxC y cobro."

    def add_arguments(self, parser):
        parser.add_argument('--empresa', type=int, required=True)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        from django.contrib.auth.models import User
        from admon_empresas.models import Empresa, Sucursal, Impuesto, Moneda
        from admon_ventas.models import Cliente, Pedido, DetallePedido
        from admon_inventarios.models import (Producto, Existencia, Almacen, Ubicacion,
                                              Grupo, UnidadMedida)
        from admon_inventarios.services import registrar_movimiento
        from admon_finanzas.models import FacturaCliente
        from admon_finanzas import services as fin_services
        from admon_ventas import services as ventas_services

        dry = opts['dry_run']
        try:
            empresa = Empresa.objects.get(pk=opts['empresa'])
        except Empresa.DoesNotExist:
            raise CommandError(f"No existe empresa con id {opts['empresa']}.")

        sucursal = Sucursal.objects.filter(empresa=empresa, es_matriz=True).first() \
            or Sucursal.objects.filter(empresa=empresa).first()
        usuario = User.objects.filter(is_superuser=True).first()
        moneda = empresa.moneda_principal or Moneda.objects.filter(empresa=empresa).first()
        iva_def = Impuesto.objects.filter(empresa=empresa, es_default=True).first()
        alm = Almacen.objects.filter(empresa=empresa, sucursal=sucursal).exclude(codigo='CAJAS').first()
        ubic = Ubicacion.objects.filter(almacen=alm).first() if alm else None

        def cliente_de(cod):
            from django.db.models import Q
            return Cliente.objects.filter(empresa=empresa).filter(
                Q(nombre_comercial__icontains=cod) | Q(nombre_fiscal__icontains=cod)
                | Q(rfc__icontains=cod)).first()

        # ---- Validación previa ----
        problemas = []
        clientes = {}
        for _, cod, _, _ in VENTAS:
            if cod not in clientes:
                c = cliente_de(cod)
                clientes[cod] = c
                if not c:
                    problemas.append(f"Cliente '{cod}' no encontrado.")

        # Stock requerido por SKU (excluye Starlink que se crea aparte)
        req = {}
        for _, _, _, lineas in VENTAS:
            for sku, qty, _ in lineas:
                req[sku] = req.get(sku, 0) + qty
        for sku, need in req.items():
            if sku == STARLINK['sku']:
                continue
            p = Producto.objects.filter(empresa=empresa, sku=sku).first()
            if not p:
                problemas.append(f"Producto SKU {sku} no existe (¿ya importaste Amazon?).")
                continue
            disp = Existencia.objects.filter(
                producto=p, sucursal=sucursal, cantidad__gt=0).aggregate(
                s=Sum('cantidad'))['s'] or D('0')
            if disp < need:
                problemas.append(f"Stock insuficiente {sku}: requiere {need}, hay {disp}.")

        ya = [f for f, *_ in VENTAS if Pedido.objects.filter(empresa=empresa, folio=f).exists()]
        if ya:
            problemas.append(f"Ya existen pedidos: {', '.join(ya)} (bórralos si quieres recargar).")

        self.stdout.write(self.style.WARNING(
            f"\n{'(DRY-RUN) ' if dry else ''}Ventas a cargar en {empresa.nombre_fiscal}:"))
        for folio, cod, fpago, lineas in VENTAS:
            tot = sum(D(p) * q for _, q, p in lineas)
            tot *= D('1.16')
            estado_pago = f"cobro {fpago}" if fpago else "PENDIENTE (refacturada)"
            self.stdout.write(f"  {folio} → {cod} · {len(lineas)} línea(s) · "
                              f"${tot.quantize(CENT)} c/IVA · {estado_pago}")

        if problemas:
            self.stdout.write(self.style.ERROR("\nPROBLEMAS:"))
            for p in problemas:
                self.stdout.write(self.style.ERROR(f"  - {p}"))
            self.stdout.write(self.style.ERROR("\nCorrige lo anterior antes de ejecutar."))
            return
        if dry:
            self.stdout.write(self.style.SUCCESS("\nDry-run OK: sin problemas. Ejecuta sin --dry-run."))
            return

        with transaction.atomic():
            # Starlink: crear producto + stock si hace falta
            need_star = req.get(STARLINK['sku'], 0)
            if need_star:
                prod_star = Producto.objects.filter(empresa=empresa, sku=STARLINK['sku']).first()
                if not prod_star:
                    grupo = Grupo.objects.filter(empresa=empresa, es_inventariable=True).first() \
                        or Grupo.objects.filter(empresa=empresa).first()
                    pza = UnidadMedida.objects.filter(empresa=empresa, codigo='PZA').first() \
                        or UnidadMedida.objects.filter(empresa=empresa).first()
                    prod_star = Producto.objects.create(
                        empresa=empresa, sku=STARLINK['sku'], nombre=STARLINK['nombre'],
                        costo_unitario=D(STARLINK['costo']), precio_venta=D('2833.45'),
                        grupo=grupo, unidad_medida=pza, impuesto=iva_def,
                        alcance='GLOBAL', es_comprable=True, es_vendible=True, activo=True)
                disp = Existencia.objects.filter(producto=prod_star, sucursal=sucursal,
                    cantidad__gt=0).aggregate(s=Sum('cantidad'))['s'] or D('0')
                if disp < need_star:
                    registrar_movimiento(
                        empresa=empresa, sucursal=sucursal, producto=prod_star, ubicacion=ubic,
                        tipo='AJUSTE_POS', origen='AJUSTE', cantidad=need_star - disp,
                        usuario=usuario, costo_unitario=D(STARLINK['costo']),
                        referencia='ALTA-ML', notas='Compra Mercado Libre (alta manual)')

            ultimo = Pedido.objects.filter(empresa=empresa).order_by('consecutivo').last()
            consec = ultimo.consecutivo if ultimo else 0

            for folio, cod, fpago, lineas in VENTAS:
                cliente = clientes[cod]
                consec += 1
                emision = fpago or date(2026, 5, 29)
                pedido = Pedido.objects.create(
                    empresa=empresa, sucursal=sucursal, cliente=cliente, moneda=moneda,
                    folio=folio, consecutivo=consec, estado='ENTREGADO', origen='MANUAL',
                    genera_cxc=True, creado_por=usuario, notas='Carga ventas pendientes')
                Pedido.objects.filter(pk=pedido.pk).update(fecha_emision=emision)

                subtotal = D('0'); imp_total = D('0')
                for sku, qty, precio in lineas:
                    prod = Producto.objects.get(empresa=empresa, sku=sku)
                    precio = D(precio)
                    det = DetallePedido.objects.create(
                        pedido=pedido, producto=prod, cantidad=qty, cantidad_entregada=qty,
                        precio_unitario=precio, impuesto=iva_def, iva_porcentaje=D('16'))
                    # Salida de inventario FIFO
                    restante = D(qty)
                    for ex in Existencia.objects.filter(
                            producto=prod, sucursal=sucursal, cantidad__gt=0).order_by('id'):
                        if restante <= 0:
                            break
                        usar = min(restante, ex.cantidad)
                        registrar_movimiento(
                            empresa=empresa, sucursal=sucursal, producto=prod,
                            ubicacion=ex.ubicacion, tipo='VENTA', origen='VENTA',
                            cantidad=usar, usuario=usuario, lote=ex.lote, serie=ex.serie,
                            referencia=folio, notas=f"Venta a {cliente}")
                        restante -= usar
                    sub = precio * qty
                    subtotal += sub
                    imp_total += sub * D('0.16')

                subtotal = subtotal.quantize(CENT); imp_total = imp_total.quantize(CENT)
                pedido.subtotal = subtotal
                pedido.impuestos = imp_total
                pedido.total = subtotal + imp_total
                pedido.save(update_fields=['subtotal', 'impuestos', 'total'])

                cxc = FacturaCliente.objects.create(
                    empresa=empresa, pedido=pedido, cliente=cliente,
                    folio=ventas_services._siguiente_folio_cxc(empresa),
                    fecha_emision=emision, moneda=moneda,
                    subtotal=subtotal, impuestos=imp_total, total=subtotal + imp_total,
                    registrada_por=usuario)

                if fpago:
                    fin_services.registrar_cobro(
                        empresa=empresa, cliente=cliente, fecha=fpago, moneda=moneda,
                        metodo=None, usuario=usuario,
                        aplicaciones=[{'factura': cxc, 'monto_aplicado': cxc.total, 'tipo_cambio': '1'}],
                        referencia=f"Pago {cod}", notas='Carga ventas pendientes')

        self.stdout.write(self.style.SUCCESS(
            f"\nListo. {len(VENTAS)} pedidos cargados con su CxC; cobros aplicados a las pagadas."))
