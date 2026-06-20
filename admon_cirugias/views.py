from datetime import datetime

from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse

from admon_empresas.models import Moneda
from admon_inventarios.models import InstanciaKit, SalidaKit, Producto
from admon_inventarios.services import (registrar_retorno_kit, StockInsuficiente,
                                        enviar_caja_a_cirugia)
from admon_ventas.models import Cliente
from .models import Doctor, Hospital, SolicitudCirugia
from . import import_catalogos as IC
from . import services


def _ctx(request):
    if not request.empresa:
        messages.warning(request, "No hay una empresa activa.")
        return None
    if not request.sucursal_activa:
        messages.warning(request, "No hay una sucursal activa. Selecciona una sede arriba.")
        return None
    return request.empresa, request.sucursal_activa


def _xlsx(contenido, filename):
    resp = HttpResponse(
        contenido, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp


# ------------------------------------------------------------------ DOCTORES
class DoctoresView(LoginRequiredMixin, View):
    template_name = 'admon_cirugias/doctores.html'

    def get(self, request):
        ctx = _ctx(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        return render(request, self.template_name, {
            'doctores': Doctor.objects.filter(empresa=empresa),
            'sucursal_activa': sucursal, 'seccion': 'cirugias',
        })

    def post(self, request):
        ctx = _ctx(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        action = request.POST.get('action')
        if action == 'delete':
            Doctor.objects.filter(id=request.POST.get('item_id'), empresa=empresa).delete()
            messages.success(request, "Doctor eliminado.")
            return redirect('admon_cirugias:doctores')
        item_id = request.POST.get('item_id')
        d = Doctor.objects.filter(id=item_id, empresa=empresa).first() if item_id else Doctor(empresa=empresa)
        d.nombre = request.POST.get('nombre', '').strip()
        d.rfc = request.POST.get('rfc', '').strip()
        d.email = request.POST.get('email') or None
        d.telefono = request.POST.get('telefono', '').strip()
        d.celular = request.POST.get('celular', '').strip()
        d.direccion = request.POST.get('direccion', '').strip()
        d.cedula = request.POST.get('cedula', '').strip()
        if not d.nombre:
            messages.error(request, "El nombre del doctor es obligatorio.")
            return redirect('admon_cirugias:doctores')
        d.empresa = empresa
        d.save()
        messages.success(request, "Doctor guardado.")
        return redirect('admon_cirugias:doctores')


class PlantillaDoctoresView(LoginRequiredMixin, View):
    def get(self, request):
        if not request.user.is_superuser:
            messages.error(request, "Solo el administrador puede descargar la plantilla.")
            return redirect('admon_cirugias:doctores')
        return _xlsx(IC.generar_plantilla_doctores(True), 'plantilla_doctores.xlsx')


class ImportarDoctoresView(LoginRequiredMixin, View):
    def post(self, request):
        ctx = _ctx(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        if not request.user.is_superuser:
            messages.error(request, "Solo el administrador puede hacer carga masiva.")
            return redirect('admon_cirugias:doctores')
        archivo = request.FILES.get('archivo')
        if not archivo or not archivo.name.lower().endswith('.xlsx'):
            messages.error(request, "Selecciona un archivo .xlsx.")
            return redirect('admon_cirugias:doctores')
        try:
            res = IC.importar_doctores(archivo, empresa)
        except Exception as e:
            messages.error(request, f"No se pudo procesar: {e}")
            return redirect('admon_cirugias:doctores')
        messages.success(request, f"Doctores: {res['creados']} nuevos, {res['actualizados']} actualizados.")
        for err in res['errores'][:10]:
            messages.warning(request, err)
        return redirect('admon_cirugias:doctores')


# ----------------------------------------------------------------- HOSPITALES
class HospitalesView(LoginRequiredMixin, View):
    template_name = 'admon_cirugias/hospitales.html'

    def get(self, request):
        ctx = _ctx(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        return render(request, self.template_name, {
            'hospitales': Hospital.objects.filter(empresa=empresa),
            'sucursal_activa': sucursal, 'seccion': 'cirugias',
        })

    def post(self, request):
        ctx = _ctx(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        action = request.POST.get('action')
        if action == 'delete':
            Hospital.objects.filter(id=request.POST.get('item_id'), empresa=empresa).delete()
            messages.success(request, "Hospital eliminado.")
            return redirect('admon_cirugias:hospitales')
        item_id = request.POST.get('item_id')
        h = Hospital.objects.filter(id=item_id, empresa=empresa).first() if item_id else Hospital(empresa=empresa)
        h.nombre = request.POST.get('nombre', '').strip()
        h.codigo = request.POST.get('codigo', '').strip()
        h.ciudad = request.POST.get('ciudad', '').strip()
        if not h.nombre:
            messages.error(request, "El nombre del hospital es obligatorio.")
            return redirect('admon_cirugias:hospitales')
        h.empresa = empresa
        h.save()
        messages.success(request, "Hospital guardado.")
        return redirect('admon_cirugias:hospitales')


class PlantillaHospitalesView(LoginRequiredMixin, View):
    def get(self, request):
        if not request.user.is_superuser:
            messages.error(request, "Solo el administrador puede descargar la plantilla.")
            return redirect('admon_cirugias:hospitales')
        return _xlsx(IC.generar_plantilla_hospitales(True), 'plantilla_hospitales.xlsx')


class ImportarHospitalesView(LoginRequiredMixin, View):
    def post(self, request):
        ctx = _ctx(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        if not request.user.is_superuser:
            messages.error(request, "Solo el administrador puede hacer carga masiva.")
            return redirect('admon_cirugias:hospitales')
        archivo = request.FILES.get('archivo')
        if not archivo or not archivo.name.lower().endswith('.xlsx'):
            messages.error(request, "Selecciona un archivo .xlsx.")
            return redirect('admon_cirugias:hospitales')
        try:
            res = IC.importar_hospitales(archivo, empresa)
        except Exception as e:
            messages.error(request, f"No se pudo procesar: {e}")
            return redirect('admon_cirugias:hospitales')
        messages.success(request, f"Hospitales: {res['creados']} nuevos, {res['actualizados']} actualizados.")
        for err in res['errores'][:10]:
            messages.warning(request, err)
        return redirect('admon_cirugias:hospitales')


# --------------------------------------------------------------- SOLICITUDES
class SolicitudesView(LoginRequiredMixin, View):
    template_name = 'admon_cirugias/solicitudes.html'

    def get(self, request):
        ctx = _ctx(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        return render(request, self.template_name, {
            'solicitudes': SolicitudCirugia.objects.filter(empresa=empresa, sucursal=sucursal).select_related(
                'doctor', 'hospital', 'cliente'),
            'sucursal_activa': sucursal, 'seccion': 'cirugias',
        })


class NuevaSolicitudView(LoginRequiredMixin, View):
    template_name = 'admon_cirugias/solicitud_form.html'

    def get(self, request):
        ctx = _ctx(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        return render(request, self.template_name, {
            'doctores': Doctor.objects.filter(empresa=empresa, activo=True),
            'hospitales': Hospital.objects.filter(empresa=empresa, activo=True),
            'clientes': Cliente.objects.filter(empresa=empresa, activo=True),
            'sucursal_activa': sucursal, 'seccion': 'cirugias',
        })

    def post(self, request):
        ctx = _ctx(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        ultimo = SolicitudCirugia.objects.filter(empresa=empresa, sucursal=sucursal).order_by('consecutivo').last()
        consec = (ultimo.consecutivo + 1) if ultimo else 1
        folio = f"{sucursal.codigo_sucursal or 'CIR'}-C{datetime.now().strftime('%y')}-{consec:05d}"
        sol = SolicitudCirugia.objects.create(
            empresa=empresa, sucursal=sucursal, folio=folio, consecutivo=consec,
            paciente=request.POST.get('paciente', '').strip(),
            doctor_id=request.POST.get('doctor') or None,
            hospital_id=request.POST.get('hospital') or None,
            fecha_cirugia=request.POST.get('fecha_cirugia') or None,
            cliente_id=request.POST.get('cliente') or None,
            comentario=request.POST.get('comentario', ''),
            estado='SOLICITADA', creado_por=request.user,
        )
        messages.success(request, f"Solicitud de cirugía {sol.folio} creada.")
        return redirect('admon_cirugias:solicitud_detalle', pk=sol.pk)


class SolicitudDetalleView(LoginRequiredMixin, View):
    template_name = 'admon_cirugias/solicitud_detalle.html'

    def get(self, request, pk):
        ctx = _ctx(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        sol = get_object_or_404(
            SolicitudCirugia.objects.select_related('doctor', 'hospital', 'cliente', 'pedido'),
            pk=pk, empresa=empresa)

        # Detecta liquidación: si alguna salida ligada ya generó pedido
        salidas = sol.salidas.select_related('instancia_kit__kit', 'pedido_generado').all()
        pedido = next((s.pedido_generado for s in salidas if s.pedido_generado_id), None)
        if pedido and sol.estado != 'LIQUIDADA':
            sol.estado = 'LIQUIDADA'
            sol.pedido = pedido
            sol.save(update_fields=['estado', 'pedido'])

        # Auto-corrige el estado: "Surtida" solo si hay salidas activas (no canceladas).
        # Si cancelaste/eliminaste la salida, vuelve a "Solicitada".
        if sol.estado in ('SURTIDA', 'ENVIADA'):
            activas = [s for s in salidas if s.estado != 'CANCELADA']
            if not activas:
                sol.estado = 'SOLICITADA'
                sol.save(update_fields=['estado'])

        hay_retornadas = any(s.estado == 'RETORNADA' for s in salidas)
        return render(request, self.template_name, {
            'solicitud': sol,
            'salidas': salidas,
            'hay_retornadas': hay_retornadas,
            'cajas_disponibles': InstanciaKit.objects.filter(
                sucursal_actual=sucursal, estado='DISPONIBLE', kit__activo=True).select_related('kit'),
            'sucursal_activa': sucursal, 'seccion': 'cirugias',
        })

    def post(self, request, pk):
        ctx = _ctx(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        sol = get_object_or_404(SolicitudCirugia, pk=pk, empresa=empresa)
        accion = request.POST.get('accion')

        if accion == 'surtir':
            caja = get_object_or_404(
                InstanciaKit, id=request.POST.get('instancia_kit'),
                sucursal_actual=sucursal, estado='DISPONIBLE')
            salida = SalidaKit.objects.create(
                empresa=empresa, instancia_kit=caja, sucursal_origen=sucursal,
                hospital_cliente=sol.hospital.nombre if sol.hospital else '—',
                doctor_responsable=sol.doctor.nombre if sol.doctor else None,
                numero_cirugia=sol.folio,
                paciente_referencia=sol.paciente or None,
                cliente=sol.cliente,
                creado_por=request.user,
                notas=f"Cirugía {sol.folio}",
            )
            try:
                # La caja sale con TODO su contenido actual (lo que trae cargado)
                enviar_caja_a_cirugia(salida=salida, usuario=request.user)
            except (ValueError, StockInsuficiente) as e:
                salida.delete()
                messages.error(request, f"No se pudo surtir: {e}")
                return redirect('admon_cirugias:solicitud_detalle', pk=pk)
            sol.salidas.add(salida)
            if sol.estado == 'SOLICITADA':
                sol.estado = 'SURTIDA'
                sol.save(update_fields=['estado'])
            messages.success(request, f"Caja {caja.codigo_caja} enviada a la cirugía con su contenido.")
            return redirect('admon_cirugias:solicitud_detalle', pk=pk)

        elif accion == 'cancelar' and sol.estado in ('SOLICITADA',):
            sol.estado = 'CANCELADA'
            sol.save(update_fields=['estado'])
            messages.info(request, f"{sol.folio} cancelada.")
        else:
            messages.error(request, "Acción no válida para el estado actual.")
        return redirect('admon_cirugias:solicitud_detalle', pk=pk)


class RegresoSalidaView(LoginRequiredMixin, View):
    """Captura el regreso de material de una caja de la cirugía
    (consumo = enviado − regresado). Vive dentro del módulo de cirugías."""
    template_name = 'admon_cirugias/regreso.html'

    def get(self, request, pk, salida_id):
        ctx = _ctx(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        sol = get_object_or_404(SolicitudCirugia, pk=pk, empresa=empresa)
        salida = get_object_or_404(sol.salidas.all(), id=salida_id)
        return render(request, self.template_name, {
            'solicitud': sol, 'salida': salida,
            'contenido': salida.contenido.select_related('producto', 'lote', 'serie'),
            'sucursal_activa': sucursal, 'seccion': 'cirugias',
        })

    def post(self, request, pk, salida_id):
        ctx = _ctx(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        sol = get_object_or_404(SolicitudCirugia, pk=pk, empresa=empresa)
        salida = get_object_or_404(sol.salidas.all(), id=salida_id)
        if salida.estado not in ('ENVIADA', 'EN_USO'):
            messages.error(request, "Esta caja no está en estado de regreso.")
            return redirect('admon_cirugias:solicitud_detalle', pk=pk)
        retornos = {item.id: (request.POST.get(f'ret_{item.id}') or '0')
                    for item in salida.contenido.all()}
        cobrados = {item.id: request.POST.get(f'cob_{item.id}')
                    for item in salida.contenido.all()}
        try:
            registrar_retorno_kit(salida=salida, retornos=retornos,
                                  cobrados=cobrados, usuario=request.user)
        except (ValueError, StockInsuficiente) as e:
            messages.error(request, f"Error: {e}")
            return redirect('admon_cirugias:regreso_salida', pk=pk, salida_id=salida_id)
        messages.success(request, f"Regreso de {salida.folio} registrado. El consumo quedó listo para liquidar.")
        return redirect('admon_cirugias:solicitud_detalle', pk=pk)


class FinalizarCirugiaView(LoginRequiredMixin, View):
    """Almacén: confirma el consumo (paciente editable) y finaliza la cirugía.
    No genera pedido ni toca dinero — la deja 'Por facturar' para ventas."""
    template_name = 'admon_cirugias/finalizar.html'

    def get(self, request, pk):
        ctx = _ctx(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        sol = get_object_or_404(
            SolicitudCirugia.objects.select_related('cliente', 'doctor', 'hospital'), pk=pk, empresa=empresa)
        salidas = sol.salidas.filter(estado='RETORNADA').prefetch_related('contenido__producto')
        return render(request, self.template_name, {
            'solicitud': sol, 'salidas': salidas,
            'sucursal_activa': sucursal, 'seccion': 'cirugias',
        })

    def post(self, request, pk):
        ctx = _ctx(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        sol = get_object_or_404(SolicitudCirugia, pk=pk, empresa=empresa)
        # El paciente puede corregirse al finalizar (el doctor avisa al regresar)
        paciente = request.POST.get('paciente')
        if paciente is not None and paciente.strip() != (sol.paciente or ''):
            sol.paciente = paciente.strip()
            sol.save(update_fields=['paciente'])
        try:
            services.finalizar_cirugia(solicitud=sol, usuario=request.user)
        except services.ErrorLiquidacion as e:
            messages.error(request, str(e))
            return redirect('admon_cirugias:finalizar_cirugia', pk=pk)
        messages.success(request, f"Cirugía {sol.folio} finalizada. Pasó a Ventas para generar el pedido.")
        return redirect('admon_cirugias:solicitud_detalle', pk=pk)
