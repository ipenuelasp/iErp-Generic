import decimal
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
        from admon_empresas import listas
        from django.urls import reverse
        res = listas.construir(
            request, Doctor.objects.filter(empresa=empresa).order_by('nombre'),
            placeholder='Nombre, RFC, cédula, email o teléfono',
            search_header=('nombre', 'rfc', 'cedula', 'email', 'telefono', 'celular'),
            clear_url=reverse('admon_cirugias:doctores'),
            export_nombre='doctores',
            export_order=('nombre',),
            export_columnas=[
                ('Nombre', 'nombre'), ('RFC', 'rfc'), ('Cédula', 'cedula'),
                ('Email', 'email'), ('Teléfono', 'telefono'), ('Celular', 'celular')],
        )
        if res['export']:
            return res['export']
        return render(request, self.template_name, {
            'doctores': res['page_obj'], 'page_obj': res['page_obj'],
            'totales': res['totales'], 'lista': res['lista'],
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
        from admon_empresas import listas
        from django.urls import reverse
        res = listas.construir(
            request, Hospital.objects.filter(empresa=empresa).order_by('nombre'),
            placeholder='Nombre, código o ciudad',
            search_header=('nombre', 'codigo', 'ciudad'),
            exactos={'activo': 'activo'},
            filtros_ui=[
                {'name': 'activo', 'label': 'Estatus', 'tipo': 'select', 'todos': 'Todos',
                 'opciones': [('1', 'Activos'), ('0', 'Inactivos')]},
            ],
            clear_url=reverse('admon_cirugias:hospitales'),
            export_nombre='hospitales',
            export_order=('nombre',),
            export_columnas=[
                ('Código', 'codigo'), ('Nombre', 'nombre'), ('Ciudad', 'ciudad'),
                ('Activo', lambda o: 'Sí' if o.activo else 'No')],
        )
        if res['export']:
            return res['export']
        return render(request, self.template_name, {
            'hospitales': res['page_obj'], 'page_obj': res['page_obj'],
            'totales': res['totales'], 'lista': res['lista'],
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
        from admon_empresas import listas
        from django.urls import reverse
        qs = SolicitudCirugia.objects.filter(
            empresa=empresa, sucursal=sucursal).select_related('doctor', 'hospital', 'cliente')
        res = listas.construir(
            request, qs,
            placeholder='Folio, paciente, doctor, hospital o cliente',
            search_header=('folio', 'paciente', 'doctor__nombre', 'hospital__nombre',
                           'cliente__nombre_fiscal', 'cliente__nombre_comercial'),
            date_field='fecha_cirugia',
            exactos={'estado': 'estado'},
            filtros_ui=[
                {'name': 'estado', 'label': 'Estado', 'tipo': 'select',
                 'opciones': SolicitudCirugia.ESTADO_CHOICES},
                {'name': 'desde', 'label': 'Cirugía desde', 'tipo': 'date'},
                {'name': 'hasta', 'label': 'Cirugía hasta', 'tipo': 'date'},
            ],
            clear_url=reverse('admon_cirugias:solicitudes'),
            export_nombre='solicitudes_cirugia',
            export_order=('-id',),
            export_columnas=[
                ('Folio', 'folio'), ('Paciente', 'paciente'),
                ('Doctor', lambda o: str(o.doctor) if o.doctor else ''),
                ('Hospital', lambda o: str(o.hospital) if o.hospital else ''),
                ('Cliente', lambda o: str(o.cliente) if o.cliente else ''),
                ('Cirugía', lambda o: o.fecha_cirugia.strftime('%d/%m/%Y') if o.fecha_cirugia else ''),
                ('Estado', 'get_estado_display')],
        )
        if res['export']:
            return res['export']
        return render(request, self.template_name, {
            'solicitudes': res['page_obj'], 'page_obj': res['page_obj'],
            'totales': res['totales'], 'lista': res['lista'],
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


def _fmt_cant(x):
    return f"{x:.2f}".rstrip('0').rstrip('.')


def _resumen_caja(caja):
    """Resumen del contenido de una caja para el selector visual de surtido."""
    cont = list(caja.contenido())
    agg = {}
    for e in cont:
        d = agg.setdefault(e.producto_id, {'sku': e.producto.sku, 'nombre': e.producto.nombre,
                                           'cant': decimal.Decimal('0')})
        d['cant'] += e.cantidad
    items = [{'sku': v['sku'], 'nombre': v['nombre'], 'cant': _fmt_cant(v['cant'])}
             for v in agg.values()]
    total = sum((e.cantidad for e in cont), decimal.Decimal('0'))
    return {
        'id': caja.id, 'codigo': caja.codigo_caja, 'nombre': caja.nombre_display,
        'num': len(items), 'piezas': _fmt_cant(total), 'items': items,
    }


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
        salidas = list(sol.salidas.select_related(
            'instancia_kit__kit', 'instancia_kit__caja_contenedora', 'pedido_generado').all())
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

        # Agrupa las salidas en árbol: la caja de cirugía (padre) con sus
        # tornilleras (hijas) anidadas debajo.
        salida_por_box = {s.instancia_kit_id: s for s in salidas}
        for s in salidas:
            s.hijas_salidas = []
        salidas_arbol = []
        for s in salidas:
            pid = s.instancia_kit.caja_contenedora_id
            padre = salida_por_box.get(pid) if pid else None
            if padre and padre is not s:
                padre.hijas_salidas.append(s)
            else:
                salidas_arbol.append(s)

        # Cajas disponibles para surtir: de nivel superior (no anidadas). Se
        # incluyen tanto las basadas en plantilla como las armadas libremente.
        cajas_disponibles = InstanciaKit.objects.filter(
            sucursal_actual=sucursal, estado='DISPONIBLE', caja_contenedora__isnull=True
        ).select_related('kit').prefetch_related('cajas_hijas')

        # Selector visual: cada caja con su contenido y el de sus tornilleras.
        puede_surtir = sol.estado in ('SOLICITADA', 'SURTIDA')
        cajas_surtir = []
        if puede_surtir:
            for c in cajas_disponibles:
                info = _resumen_caja(c)
                info['tornilleras'] = [
                    _resumen_caja(h) for h in c.cajas_hijas.filter(estado='DISPONIBLE')]
                cajas_surtir.append(info)

        return render(request, self.template_name, {
            'solicitud': sol,
            'salidas': salidas,
            'salidas_arbol': salidas_arbol,
            'hay_retornadas': hay_retornadas,
            'cajas_disponibles': cajas_disponibles,
            'cajas_surtir': cajas_surtir,
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

            def _crear_salida(cja):
                return SalidaKit.objects.create(
                    empresa=empresa, instancia_kit=cja, sucursal_origen=sucursal,
                    hospital_cliente=sol.hospital.nombre if sol.hospital else '—',
                    doctor_responsable=sol.doctor.nombre if sol.doctor else None,
                    numero_cirugia=sol.folio,
                    paciente_referencia=sol.paciente or None,
                    cliente=sol.cliente,
                    creado_por=request.user,
                    notas=f"Cirugía {sol.folio}",
                )

            # Tornilleras (cajas hijas) disponibles que van dentro de esta caja.
            hijas = list(caja.cajas_hijas.filter(estado='DISPONIBLE'))

            salida = _crear_salida(caja)
            try:
                # La caja padre sale con su material suelto; si solo es contenedora
                # (sin stock propio) pero trae tornilleras, se permite vacía.
                enviar_caja_a_cirugia(salida=salida, usuario=request.user,
                                      permitir_vacia=bool(hijas))
            except (ValueError, StockInsuficiente) as e:
                salida.delete()
                messages.error(request, f"No se pudo surtir: {e}")
                return redirect('admon_cirugias:solicitud_detalle', pk=pk)
            sol.salidas.add(salida)

            enviadas = [caja.codigo_caja]
            fallidas = []
            for h in hijas:
                sh = _crear_salida(h)
                try:
                    enviar_caja_a_cirugia(salida=sh, usuario=request.user)
                    sol.salidas.add(sh)
                    enviadas.append(h.codigo_caja)
                except (ValueError, StockInsuficiente) as e:
                    sh.delete()
                    fallidas.append(f"{h.codigo_caja} ({e})")

            if sol.estado == 'SOLICITADA':
                sol.estado = 'SURTIDA'
                sol.save(update_fields=['estado'])
            messages.success(
                request,
                f"Enviado a la cirugía: {', '.join(enviadas)}."
                + (f" Tornilleras vacías no enviadas: {'; '.join(fallidas)}." if fallidas else ""))
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
