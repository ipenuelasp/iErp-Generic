import decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.utils import timezone

from admon_empresas.models import Sucursal
from .models import (
    Producto, Ubicacion, Existencia,
    SolicitudTraspaso, DetalleTraspaso, TrazabilidadTraspaso,
)
from .views import _contexto_valido, productos_disponibles_en
from .services import registrar_movimiento, StockInsuficiente


class TraspasosView(LoginRequiredMixin, View):
    """Listado de traspasos entrantes (me envían) y salientes (yo envío)."""
    template_name = 'admon_inventarios/traspasos.html'

    def get(self, request):
        ctx = _contexto_valido(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx

        context = {
            # Yo solicité material (soy destino): espero que el origen me lo envíe
            'entrantes': SolicitudTraspaso.objects.filter(sucursal_destino=sucursal).select_related(
                'sucursal_origen', 'sucursal_destino', 'solicitado_por'),
            # Me solicitaron material (soy origen): debo aprobar/enviar
            'salientes': SolicitudTraspaso.objects.filter(sucursal_origen=sucursal).select_related(
                'sucursal_origen', 'sucursal_destino', 'solicitado_por'),
            'otras_sucursales': Sucursal.objects.filter(empresa=empresa).exclude(id=sucursal.id),
            'productos': productos_disponibles_en(empresa, sucursal),
            'sucursal_activa': sucursal,
            'seccion': 'inventarios',
        }
        return render(request, self.template_name, context)

    def post(self, request):
        """Crear nueva solicitud de traspaso (yo soy el destino que pide)."""
        ctx = _contexto_valido(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx

        origen_id = request.POST.get('sucursal_origen')
        producto_ids = request.POST.getlist('producto_id[]')
        cantidades = request.POST.getlist('cantidad[]')

        origen = get_object_or_404(Sucursal, id=origen_id, empresa=empresa)
        if origen.id == sucursal.id:
            messages.error(request, "El origen no puede ser la misma sucursal.")
            return redirect('admon_inventarios:traspasos')

        partidas = []
        for i, pid in enumerate(producto_ids):
            cant = decimal.Decimal(cantidades[i] or '0')
            if pid and cant > 0:
                partidas.append((pid, cant))

        if not partidas:
            messages.error(request, "Agrega al menos una partida con cantidad mayor a 0.")
            return redirect('admon_inventarios:traspasos')

        solicitud = SolicitudTraspaso.objects.create(
            empresa=empresa,
            sucursal_origen=origen,
            sucursal_destino=sucursal,
            solicitado_por=request.user,
            notas_solicitud=request.POST.get('notas'),
        )
        for pid, cant in partidas:
            producto = get_object_or_404(Producto, id=pid, empresa=empresa)
            DetalleTraspaso.objects.create(
                solicitud=solicitud, producto=producto, cantidad_solicitada=cant,
            )

        messages.success(request, f"Solicitud {solicitud.folio} enviada a {origen.nombre}.")
        return redirect('admon_inventarios:traspasos')


class TraspasoDetalleView(LoginRequiredMixin, View):
    """Detalle de una solicitud con las acciones según estado y rol de la sucursal."""
    template_name = 'admon_inventarios/traspaso_detalle.html'

    def get(self, request, pk):
        ctx = _contexto_valido(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx

        solicitud = get_object_or_404(
            SolicitudTraspaso.objects.select_related('sucursal_origen', 'sucursal_destino'),
            pk=pk, empresa=empresa,
        )
        soy_origen = solicitud.sucursal_origen_id == sucursal.id
        soy_destino = solicitud.sucursal_destino_id == sucursal.id

        # Existencias disponibles en el origen por producto (para armar el envío)
        existencias_por_detalle = {}
        if soy_origen and solicitud.estado == 'APROBADO':
            for det in solicitud.detalles.all():
                existencias_por_detalle[det.id] = Existencia.objects.filter(
                    producto=det.producto,
                    sucursal=sucursal,
                    cantidad__gt=0,
                ).select_related('ubicacion', 'ubicacion__almacen', 'lote', 'serie')

        ubicaciones_destino = []
        if soy_destino and solicitud.estado == 'EN_TRANSITO':
            ubicaciones_destino = Ubicacion.objects.filter(
                almacen__sucursal=sucursal, activa=True
            ).select_related('almacen')

        context = {
            'solicitud': solicitud,
            'detalles': solicitud.detalles.select_related('producto').prefetch_related(
                'trazabilidad__lote', 'trazabilidad__serie', 'trazabilidad__ubicacion_origen'),
            'soy_origen': soy_origen,
            'soy_destino': soy_destino,
            'existencias_por_detalle': existencias_por_detalle,
            'ubicaciones_destino': ubicaciones_destino,
            'sucursal_activa': sucursal,
            'seccion': 'inventarios',
        }
        return render(request, self.template_name, context)

    @transaction.atomic
    def post(self, request, pk):
        ctx = _contexto_valido(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx

        solicitud = get_object_or_404(SolicitudTraspaso, pk=pk, empresa=empresa)
        accion = request.POST.get('accion')
        soy_origen = solicitud.sucursal_origen_id == sucursal.id
        soy_destino = solicitud.sucursal_destino_id == sucursal.id

        try:
            if accion == 'aprobar' and soy_origen and solicitud.estado == 'SOLICITADO':
                solicitud.estado = 'APROBADO'
                solicitud.aprobado_por = request.user
                solicitud.fecha_aprobacion = timezone.now()
                solicitud.save()
                messages.success(request, f"{solicitud.folio} aprobado. Ahora confirma el envío.")

            elif accion == 'rechazar' and soy_origen and solicitud.estado == 'SOLICITADO':
                solicitud.estado = 'RECHAZADO'
                solicitud.aprobado_por = request.user
                solicitud.fecha_aprobacion = timezone.now()
                solicitud.notas_envio = request.POST.get('motivo')
                solicitud.save()
                messages.info(request, f"{solicitud.folio} rechazado.")

            elif accion == 'cancelar' and soy_destino and solicitud.estado in ('SOLICITADO', 'APROBADO'):
                solicitud.estado = 'CANCELADO'
                solicitud.save()
                messages.info(request, f"{solicitud.folio} cancelado.")

            elif accion == 'enviar' and soy_origen and solicitud.estado == 'APROBADO':
                self._procesar_envio(request, empresa, sucursal, solicitud)
                messages.success(request, f"{solicitud.folio} en tránsito hacia {solicitud.sucursal_destino.nombre}.")

            elif accion == 'recibir' and soy_destino and solicitud.estado == 'EN_TRANSITO':
                self._procesar_recepcion(request, empresa, sucursal, solicitud)
                messages.success(request, f"{solicitud.folio} recibido en {sucursal.nombre}.")

            else:
                messages.error(request, "Acción no permitida para el estado actual o tu sucursal.")

        except (ValueError, StockInsuficiente) as e:
            transaction.set_rollback(True)
            messages.error(request, f"Error: {e}")

        return redirect('admon_inventarios:traspaso_detalle', pk=pk)

    def _procesar_envio(self, request, empresa, sucursal, solicitud):
        """El origen confirma qué existencias (ubicación/lote/serie) viajan."""
        hubo_envio = False
        for det in solicitud.detalles.select_related('producto'):
            exist_ids = request.POST.getlist(f'env_exist_{det.id}[]')
            cants = request.POST.getlist(f'env_cant_{det.id}[]')

            total_det = decimal.Decimal('0')
            for j, ex_id in enumerate(exist_ids):
                cant = decimal.Decimal(cants[j] or '0')
                if not ex_id or cant <= 0:
                    continue
                existencia = get_object_or_404(
                    Existencia, id=ex_id, producto=det.producto, sucursal=sucursal)

                registrar_movimiento(
                    empresa=empresa, sucursal=sucursal, producto=det.producto,
                    ubicacion=existencia.ubicacion, tipo='TRASPASO_SAL', origen='TRASPASO',
                    cantidad=cant, usuario=request.user,
                    lote=existencia.lote, serie=existencia.serie,
                    referencia=solicitud.folio,
                )
                if existencia.serie:
                    existencia.serie.estado = 'EN_TRANSITO'
                    existencia.serie.save()

                TrazabilidadTraspaso.objects.create(
                    detalle=det, lote=existencia.lote, serie=existencia.serie,
                    cantidad=cant, ubicacion_origen=existencia.ubicacion,
                )
                total_det += cant

            det.cantidad_enviada = total_det
            det.save()
            if total_det > 0:
                hubo_envio = True

        if not hubo_envio:
            raise ValueError("No se capturó ninguna cantidad a enviar.")

        solicitud.estado = 'EN_TRANSITO'
        solicitud.enviado_por = request.user
        solicitud.fecha_envio = timezone.now()
        solicitud.notas_envio = request.POST.get('notas_envio')
        solicitud.save()

    def _procesar_recepcion(self, request, empresa, sucursal, solicitud):
        """El destino confirma la entrada: cada partida a una ubicación local."""
        for det in solicitud.detalles.select_related('producto'):
            if det.cantidad_enviada <= 0:
                continue
            ubi_id = request.POST.get(f'rec_ubi_{det.id}')
            if not ubi_id:
                raise ValueError(f"Falta ubicación destino para {det.producto.nombre}.")
            ubicacion = get_object_or_404(Ubicacion, id=ubi_id, almacen__sucursal=sucursal)

            total = decimal.Decimal('0')
            for traza in det.trazabilidad.all():
                registrar_movimiento(
                    empresa=empresa, sucursal=sucursal, producto=det.producto,
                    ubicacion=ubicacion, tipo='TRASPASO_ENT', origen='TRASPASO',
                    cantidad=traza.cantidad, usuario=request.user,
                    lote=traza.lote, serie=traza.serie,
                    referencia=solicitud.folio,
                )
                if traza.serie:
                    traza.serie.estado = 'DISPONIBLE'
                    traza.serie.save()
                total += traza.cantidad

            det.cantidad_recibida = total
            det.ubicacion_destino = ubicacion
            det.save()

        solicitud.estado = 'RECIBIDO'
        solicitud.recibido_por = request.user
        solicitud.fecha_recepcion = timezone.now()
        solicitud.notas_recepcion = request.POST.get('notas_recepcion')
        solicitud.save()
