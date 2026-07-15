import decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction

from admon_inventarios.models import (
    Ubicacion, Existencia, Lote, NumeroSerie,
    RecepcionMaterial, DetalleRecepcion, SerieRecepcion,
)
from admon_inventarios.services import registrar_movimiento, StockInsuficiente
from .models import OrdenCompra, DetalleOrdenCompra
from .views import _contexto


class PendientesRecepcionView(LoginRequiredMixin, View):
    """Reporte para el almacén: órdenes de compra con material por llegar a su
    sucursal. NO muestra precios (solo cantidades). Soporta recepción parcial."""
    template_name = 'admon_compras/pendientes_recepcion.html'

    def get(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        ordenes = OrdenCompra.objects.filter(
            empresa=empresa, sucursal_destino=sucursal, estado__in=['AUTORIZADO', 'RECIBIDO']
        ).select_related('proveedor').prefetch_related('detalles__producto').order_by(
            'fecha_entrega_estimada', 'fecha_emision')

        data = []
        total_lineas = decimal.Decimal('0')
        for o in ordenes:
            pendientes = []
            for d in o.detalles.all():
                if getattr(d.producto, 'es_servicio', False):
                    continue
                restante = d.cantidad_pedida - d.cantidad_recibida
                if restante > 0:
                    pendientes.append({
                        'producto': d.producto, 'pedida': d.cantidad_pedida,
                        'recibida': d.cantidad_recibida, 'restante': restante,
                    })
            if pendientes:
                total_lineas += len(pendientes)
                data.append({'orden': o, 'pendientes': pendientes,
                             'n_lineas': len(pendientes)})

        return render(request, self.template_name, {
            'ordenes': data,
            'total_ordenes': len(data),
            'sucursal_activa': sucursal,
            'seccion': 'inventarios',
        })


class RecepcionOCView(LoginRequiredMixin, View):
    """Recibe mercancía contra una OC autorizada, actualizando el inventario
    y el avance de cada partida."""
    template_name = 'admon_compras/recepcion_oc.html'

    def get(self, request, pk):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        orden = get_object_or_404(
            OrdenCompra.objects.select_related('proveedor'),
            id=pk, empresa=empresa)

        if orden.estado not in ('AUTORIZADO', 'RECIBIDO'):
            messages.error(request, "Solo se reciben órdenes autorizadas.")
            return redirect('admon_compras:orden_detalle', pk=pk)
        if orden.sucursal_destino_id != sucursal.id:
            messages.warning(request, f"Esta OC se recibe en {orden.sucursal_destino.nombre}. Cambia de sede.")
            return redirect('admon_compras:orden_detalle', pk=pk)

        ubicaciones = Ubicacion.objects.filter(
            almacen__sucursal=sucursal, activa=True).select_related('almacen')
        if not ubicaciones.exists():
            messages.warning(request, "Crea al menos un almacén con ubicaciones para recibir.")
            return redirect('admon_inventarios:catalogos_productos')

        partidas = []
        for det in orden.detalles.select_related('producto').filter():
            if det.pendiente_por_recibir > 0:
                partidas.append(det)

        context = {
            'orden': orden,
            'partidas': partidas,
            'ubicaciones': ubicaciones,
            'sucursal_activa': sucursal,
            'seccion': 'inventarios',
        }
        return render(request, self.template_name, context)

    @transaction.atomic
    def post(self, request, pk):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        orden = get_object_or_404(OrdenCompra, id=pk, empresa=empresa)

        if orden.estado not in ('AUTORIZADO', 'RECIBIDO'):
            messages.error(request, "Solo se reciben órdenes autorizadas.")
            return redirect('admon_compras:orden_detalle', pk=pk)

        recepcion = RecepcionMaterial.objects.create(
            empresa=empresa, sucursal=sucursal, orden_compra=orden,
            proveedor_nombre=str(orden.proveedor),
            remision_proveedor=request.POST.get('remision'),
            numero_factura=request.POST.get('factura'),
            recibido_por=request.user, notas=request.POST.get('notas'),
        )

        det_ids = request.POST.getlist('detalle_oc_id[]')
        cantidades = request.POST.getlist('cantidad[]')
        ubic_ids = request.POST.getlist('ubicacion_id[]')

        try:
            for i, det_id in enumerate(det_ids):
                cant = decimal.Decimal(cantidades[i] or '0')
                if cant <= 0:
                    continue
                det_oc = get_object_or_404(DetalleOrdenCompra, id=det_id, orden=orden)
                producto = det_oc.producto
                if cant > det_oc.pendiente_por_recibir:
                    raise ValueError(
                        f"{producto.nombre}: recibes {cant} pero solo faltan "
                        f"{det_oc.pendiente_por_recibir}.")
                ubicacion = get_object_or_404(Ubicacion, id=ubic_ids[i], almacen__sucursal=sucursal)
                costo = det_oc.precio_unitario

                if producto.es_serializable:
                    series = request.POST.getlist(f'series_{det_id}[]')
                    if len(series) != int(cant):
                        raise ValueError(
                            f"{producto.nombre}: faltan series ({len(series)} de {int(cant)}).")
                    detalle = DetalleRecepcion.objects.create(
                        recepcion=recepcion, producto=producto, detalle_oc=det_oc,
                        cantidad_recibida=cant, ubicacion=ubicacion, costo_unitario=costo)
                    for s_num in series:
                        serie_obj, created = NumeroSerie.objects.get_or_create(
                            producto=producto, serie=s_num.strip())
                        if not created and Existencia.objects.filter(
                                producto=producto, serie=serie_obj, cantidad__gt=0).exists():
                            raise ValueError(f"La serie {s_num} ya está en inventario.")
                        registrar_movimiento(
                            empresa=empresa, sucursal=sucursal, producto=producto,
                            ubicacion=ubicacion, tipo='ENTRADA', origen='OC',
                            cantidad=1, usuario=request.user, serie=serie_obj,
                            referencia=orden.folio, costo_unitario=costo)
                        serie_obj.estado = 'DISPONIBLE'
                        serie_obj.save()
                        SerieRecepcion.objects.create(detalle=detalle, serie=serie_obj)
                else:
                    lote_obj = None
                    if producto.es_loteable:
                        lote_num = request.POST.get(f'lote_num_{det_id}')
                        lote_fec = request.POST.get(f'lote_fec_{det_id}')
                        if not lote_num:
                            raise ValueError(f"{producto.nombre} requiere número de lote.")
                        lote_obj, _ = Lote.objects.get_or_create(
                            producto=producto, numero_lote=lote_num.strip(),
                            defaults={'fecha_caducidad': lote_fec or None})
                    DetalleRecepcion.objects.create(
                        recepcion=recepcion, producto=producto, detalle_oc=det_oc,
                        cantidad_recibida=cant, ubicacion=ubicacion,
                        lote=lote_obj, costo_unitario=costo)
                    registrar_movimiento(
                        empresa=empresa, sucursal=sucursal, producto=producto,
                        ubicacion=ubicacion, tipo='ENTRADA', origen='OC',
                        cantidad=cant, usuario=request.user, lote=lote_obj,
                        referencia=orden.folio, costo_unitario=costo)

                det_oc.cantidad_recibida += cant
                det_oc.save()

        except (ValueError, StockInsuficiente) as e:
            transaction.set_rollback(True)
            messages.error(request, f"Error: {e}")
            return redirect('admon_compras:recepcion_oc', pk=pk)

        if not recepcion.detalles.exists():
            transaction.set_rollback(True)
            messages.error(request, "No capturaste ninguna cantidad válida.")
            return redirect('admon_compras:recepcion_oc', pk=pk)

        # Actualizar estado de la OC
        orden.estado = 'FINALIZADO' if orden.esta_recibida_completa else 'RECIBIDO'
        orden.save()
        messages.success(request, f"Recepción {recepcion.folio} aplicada a {orden.folio}.")
        return redirect('admon_compras:orden_detalle', pk=pk)
