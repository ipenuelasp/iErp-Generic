"""
Motor de tesorería: registra pagos y mantiene saldos/estados de facturas.
"""
import decimal

from django.db import transaction

from .models import Pago, AplicacionPago, FacturaProveedor, FacturaCliente


class ErrorPago(Exception):
    pass


@transaction.atomic
def registrar_pago(*, empresa, tipo, proveedor, fecha, moneda, metodo,
                   usuario, aplicaciones, cuenta_banco=None, referencia=None, notas=None):
    """Crea un pago y lo aplica a una o varias facturas.

    aplicaciones: lista de dicts {factura, monto_aplicado, tipo_cambio}
      - monto_aplicado en moneda de la factura
      - tipo_cambio: unidades de moneda_pago por 1 de moneda_factura
    Recalcula el estado de cada factura afectada.
    """
    if not aplicaciones:
        raise ErrorPago("No se capturó ninguna factura a pagar.")

    pago = Pago.objects.create(
        empresa=empresa, tipo=tipo, proveedor=proveedor, fecha=fecha,
        moneda=moneda, metodo=metodo, cuenta_banco=cuenta_banco,
        referencia=referencia, notas=notas, creado_por=usuario,
    )

    total_pago = decimal.Decimal('0')
    for ap in aplicaciones:
        factura = ap['factura']
        monto = decimal.Decimal(ap['monto_aplicado'])
        tc = decimal.Decimal(ap.get('tipo_cambio') or '1')

        if monto <= 0:
            continue
        if factura.estado == 'CANCELADA':
            raise ErrorPago(f"La factura {factura.folio} está cancelada.")
        if monto > factura.saldo:
            raise ErrorPago(
                f"El monto aplicado a {factura.folio} ({monto}) supera su saldo ({factura.saldo}).")

        AplicacionPago.objects.create(
            pago=pago, factura=factura, monto_aplicado=monto, tipo_cambio=tc)
        factura.recalcular_estado()
        total_pago += monto * tc

    if total_pago <= 0:
        transaction.set_rollback(True)
        raise ErrorPago("El pago no tiene montos válidos.")

    pago.monto = total_pago
    pago.save(update_fields=['monto'])
    return pago


@transaction.atomic
def registrar_cobro(*, empresa, cliente, fecha, moneda, metodo,
                    usuario, aplicaciones, cuenta_banco=None, referencia=None, notas=None):
    """Crea un cobro (Pago tipo INGRESO) y lo aplica a una o varias facturas
    de cliente. aplicaciones: lista de dicts {factura, monto_aplicado, tipo_cambio}
    donde factura es una FacturaCliente."""
    if not aplicaciones:
        raise ErrorPago("No se capturó ninguna factura a cobrar.")

    pago = Pago.objects.create(
        empresa=empresa, tipo=Pago.TIPO_INGRESO, cliente=cliente, fecha=fecha,
        moneda=moneda, metodo=metodo, cuenta_banco=cuenta_banco,
        referencia=referencia, notas=notas, creado_por=usuario,
    )

    total_pago = decimal.Decimal('0')
    for ap in aplicaciones:
        factura = ap['factura']
        monto = decimal.Decimal(ap['monto_aplicado'])
        tc = decimal.Decimal(ap.get('tipo_cambio') or '1')

        if monto <= 0:
            continue
        if factura.estado == 'CANCELADA':
            raise ErrorPago(f"La factura {factura.folio} está cancelada.")
        if monto > factura.saldo:
            raise ErrorPago(
                f"El monto aplicado a {factura.folio} ({monto}) supera su saldo ({factura.saldo}).")

        AplicacionPago.objects.create(
            pago=pago, factura_cliente=factura, monto_aplicado=monto, tipo_cambio=tc)
        factura.recalcular_estado()
        total_pago += monto * tc

    if total_pago <= 0:
        transaction.set_rollback(True)
        raise ErrorPago("El cobro no tiene montos válidos.")

    pago.monto = total_pago
    pago.save(update_fields=['monto'])
    return pago


def facturas_por_cobrar(empresa, cliente=None):
    qs = FacturaCliente.objects.filter(
        empresa=empresa, estado__in=['PENDIENTE', 'PARCIAL']
    ).select_related('cliente', 'moneda', 'pedido')
    if cliente:
        qs = qs.filter(cliente=cliente)
    return qs


def facturas_por_pagar(empresa, proveedor=None):
    qs = FacturaProveedor.objects.filter(
        empresa=empresa, estado__in=['PENDIENTE', 'PARCIAL']
    ).select_related('proveedor', 'moneda', 'orden_compra')
    if proveedor:
        qs = qs.filter(proveedor=proveedor)
    return qs
