"""
Flujo de cirugía dividido por rol:
  - finalizar_cirugia(): el almacenista cierra el regreso (consumo capturado),
    libera las cajas y deja la cirugía POR_FACTURAR. NO genera pedido.
  - generar_pedido_de_cirugia(): ventas toma una cirugía POR_FACTURAR y genera
    UN pedido + CxC con el consumo (consumibles usados + renta de retornables).
    Extras y comisiones se agregan después en el pedido. El stock ya se movió
    en salida/retorno del kit; aquí no se vuelve a tocar inventario.
"""
import decimal

from django.db import transaction

from admon_empresas.models import Impuesto
from admon_ventas.models import Pedido, DetallePedido
from admon_ventas.services import _crear_factura_cliente


class ErrorLiquidacion(Exception):
    pass


@transaction.atomic
def finalizar_cirugia(*, solicitud, usuario):
    """Almacén: cierra el regreso, libera las cajas y deja la cirugía lista
    para que ventas genere el pedido. No toca dinero ni inventario."""
    if solicitud.estado == 'LIQUIDADA' or solicitud.pedido_id:
        raise ErrorLiquidacion("Esta cirugía ya fue facturada.")
    salidas = list(solicitud.salidas.filter(estado='RETORNADA'))
    if not salidas:
        raise ErrorLiquidacion("No hay material retornado. Registra el regreso de cada caja primero.")
    # Libera las cajas (su material ya volvió en el regreso). El material suelto
    # no tiene caja que liberar.
    for salida in salidas:
        if salida.instancia_kit_id:
            salida.instancia_kit.estado = 'DISPONIBLE'
            salida.instancia_kit.save(update_fields=['estado'])
    solicitud.estado = 'POR_FACTURAR'
    solicitud.save(update_fields=['estado'])
    return solicitud


@transaction.atomic
def generar_pedido_de_cirugia(*, solicitud, moneda, usuario):
    """Ventas: genera el pedido + CxC del consumo de la cirugía."""
    if solicitud.pedido_id:
        raise ErrorLiquidacion("Esta cirugía ya tiene pedido generado.")
    if solicitud.estado != 'POR_FACTURAR':
        raise ErrorLiquidacion("La cirugía debe estar finalizada por almacén (Por facturar).")
    if not solicitud.cliente_id:
        raise ErrorLiquidacion("La solicitud no tiene cliente a facturar.")

    salidas = list(solicitud.salidas.filter(estado='RETORNADA'))
    if not salidas:
        raise ErrorLiquidacion("No hay material retornado por facturar.")

    empresa = solicitud.empresa
    sucursal = solicitud.sucursal
    default_imp = Impuesto.objects.filter(empresa=empresa, es_default=True).first()

    ultimo = Pedido.objects.filter(empresa=empresa, sucursal=sucursal).order_by('consecutivo').last()
    consec = (ultimo.consecutivo + 1) if ultimo else 1
    folio = f"{sucursal.codigo_sucursal or 'PED'}-CX-{consec:05d}"

    pedido = Pedido.objects.create(
        empresa=empresa, sucursal=sucursal, cliente=solicitud.cliente, moneda=moneda,
        folio=folio, consecutivo=consec, estado='ENTREGADO', origen='CIRUGIA',
        genera_cxc=True, creado_por=usuario,
        notas=f"Cirugía {solicitud.folio}"
              + (f" · {solicitud.hospital.nombre}" if solicitud.hospital else "")
              + (f" · {solicitud.paciente}" if solicitud.paciente else ""),
    )

    subtotal = decimal.Decimal('0')
    imp_total = decimal.Decimal('0')

    def add_linea(prod, tipo_linea, cant, precio):
        nonlocal subtotal, imp_total
        if cant <= 0:
            return
        imp = prod.impuesto or default_imp
        tasa = imp.tasa if imp else decimal.Decimal('0')
        es_ret = imp.es_retencion if imp else False
        sub = cant * precio
        monto = sub * (tasa / 100)
        DetallePedido.objects.create(
            pedido=pedido, producto=prod, tipo_linea=tipo_linea,
            cantidad=cant, cantidad_entregada=cant, precio_unitario=precio,
            impuesto=imp, iva_porcentaje=tasa, es_retencion=es_ret)
        subtotal += sub
        imp_total += (-monto if es_ret else monto)

    for salida in salidas:
        for item in salida.contenido.select_related('producto'):
            prod = item.producto
            if item.es_retornable:
                add_linea(prod, DetallePedido.LINEA_RENTA, item.cantidad_enviada, prod.precio_renta)
            else:
                add_linea(prod, DetallePedido.LINEA_PRODUCTO, item.cantidad_usada, prod.precio_venta)

    if not pedido.detalles.exists():
        transaction.set_rollback(True)
        raise ErrorLiquidacion("No hay consumo por facturar.")

    pedido.subtotal = subtotal
    pedido.impuestos = imp_total
    pedido.total = subtotal + imp_total
    pedido.save()

    _crear_factura_cliente(pedido, usuario, subtotal, imp_total)

    for salida in salidas:
        salida.pedido_generado = pedido
        salida.estado = 'CERRADA'
        salida.save(update_fields=['pedido_generado', 'estado'])

    solicitud.pedido = pedido
    solicitud.estado = 'LIQUIDADA'
    solicitud.save(update_fields=['pedido', 'estado'])

    return pedido
