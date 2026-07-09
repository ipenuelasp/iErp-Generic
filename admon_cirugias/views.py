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
    """Resumen del contenido de una caja + completitud contra su receta."""
    cont = list(caja.contenido())
    agg = {}
    for e in cont:
        d = agg.setdefault(e.producto_id, {'sku': e.producto.sku, 'nombre': e.producto.nombre,
                                           'cant': decimal.Decimal('0')})
        d['cant'] += e.cantidad
    items = [{'sku': v['sku'], 'nombre': v['nombre'], 'cant': _fmt_cant(v['cant'])}
             for v in agg.values()]
    total = sum((e.cantidad for e in cont), decimal.Decimal('0'))

    objetivo = caja.lineas_objetivo()  # [(producto, cantidad_objetivo, es_retornable)]
    falta_total = decimal.Decimal('0')
    faltantes = []
    detalle = []          # receta completa (actual vs objetivo) + extras, como en Armar cajas
    ids_receta = set()
    for prod, cant_obj, ret in objetivo:
        ids_receta.add(prod.id)
        act = agg.get(prod.id, {}).get('cant', decimal.Decimal('0'))
        falta = cant_obj - act
        if falta < 0:
            falta = decimal.Decimal('0')
        falta_total += falta
        detalle.append({'sku': prod.sku, 'nombre': prod.nombre, 'actual': _fmt_cant(act),
                        'objetivo': _fmt_cant(cant_obj), 'falta': _fmt_cant(falta),
                        'ret': ret, 'extra': False, 'incompleto': falta > 0})
        if falta > 0:
            faltantes.append({'sku': prod.sku, 'nombre': prod.nombre,
                              'falta': _fmt_cant(falta), 'objetivo': _fmt_cant(cant_obj)})
    for pid, v in agg.items():
        if pid not in ids_receta:
            detalle.append({'sku': v['sku'], 'nombre': v['nombre'], 'actual': _fmt_cant(v['cant']),
                            'objetivo': '', 'falta': '', 'ret': False, 'extra': True, 'incompleto': False})
    tiene_receta = bool(objetivo)
    return {
        'id': caja.id, 'codigo': caja.codigo_caja, 'nombre': caja.nombre_display,
        'num': len(items), 'piezas': _fmt_cant(total), 'items': items, 'detalle': detalle,
        'tiene_receta': tiene_receta, 'completa': tiene_receta and falta_total == 0,
        'falta_total': _fmt_cant(falta_total), 'faltantes': faltantes,
    }


def _items_enviados(salida):
    """Productos que salieron en la caja (agregado por producto), encabezado→detalle."""
    agg = {}
    for cs in salida.contenido.select_related('producto').all():
        d = agg.setdefault(cs.producto_id, {'sku': cs.producto.sku, 'nombre': cs.producto.nombre,
                                            'cant': decimal.Decimal('0'), 'ret': cs.es_retornable})
        d['cant'] += cs.cantidad_enviada
    return [{'sku': v['sku'], 'nombre': v['nombre'], 'cant': _fmt_cant(v['cant']), 'ret': v['ret']}
            for v in agg.values()]


def _arbol_salidas(salidas):
    """Agrupa salidas en árbol padre→hijas por la caja contenedora."""
    por_box = {s.instancia_kit_id: s for s in salidas}
    for s in salidas:
        s.hijas_salidas = []
    raiz = []
    for s in salidas:
        pid = s.instancia_kit.caja_contenedora_id
        padre = por_box.get(pid) if pid else None
        if padre and padre is not s:
            padre.hijas_salidas.append(s)
        else:
            raiz.append(s)
    return raiz


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

        # Separa borradores (por surtir) de las ya enviadas/en proceso.
        borradores = [s for s in salidas if s.estado == 'PREPARANDO']
        enviadas = [s for s in salidas if s.estado not in ('PREPARANDO', 'CANCELADA')]

        # Borrador: adjunta el resumen del contenido actual + completitud.
        for s in borradores:
            s.resumen = _resumen_caja(s.instancia_kit)
        # Enviadas: adjunta el resumen de lo que salió (encabezado→detalle).
        for s in enviadas:
            s.items_enviados = _items_enviados(s)

        borradores_arbol = _arbol_salidas(borradores)
        enviadas_arbol = _arbol_salidas(enviadas)

        # Cajas disponibles para surtir: de nivel superior (no anidadas), que no
        # estén ya en esta cirugía. Incluye cajas con plantilla y armadas libres.
        ya_en_sol = {s.instancia_kit_id for s in salidas if s.estado != 'CANCELADA'}
        cajas_disponibles = InstanciaKit.objects.filter(
            sucursal_actual=sucursal, estado='DISPONIBLE', caja_contenedora__isnull=True
        ).exclude(id__in=ya_en_sol).select_related('kit').prefetch_related('cajas_hijas')

        # Selector visual: cada caja con su contenido, completitud y tornilleras.
        puede_surtir = sol.estado in ('SOLICITADA', 'SURTIDA')
        cajas_surtir = []
        if puede_surtir:
            for c in cajas_disponibles:
                info = _resumen_caja(c)
                info['tornilleras'] = [
                    _resumen_caja(h) for h in c.cajas_hijas.filter(estado='DISPONIBLE')]
                cajas_surtir.append(info)

        # La solicitud se puede editar mientras no esté finalizada/liquidada.
        puede_editar = sol.estado in ('SOLICITADA', 'SURTIDA')
        ctx_edit = {}
        if puede_editar:
            ctx_edit = {
                'doctores': Doctor.objects.filter(empresa=empresa, activo=True),
                'hospitales': Hospital.objects.filter(empresa=empresa, activo=True),
                'clientes': Cliente.objects.filter(empresa=empresa, activo=True),
            }

        return render(request, self.template_name, {
            'solicitud': sol,
            'salidas': salidas,
            'borradores_arbol': borradores_arbol,
            'enviadas_arbol': enviadas_arbol,
            'hay_borradores': bool(borradores),
            'hay_retornadas': hay_retornadas,
            'cajas_surtir': cajas_surtir,
            'puede_editar': puede_editar,
            'sucursal_activa': sucursal, 'seccion': 'cirugias',
            **ctx_edit,
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

            # Se agrega como BORRADOR (PREPARANDO). El stock aún no se mueve;
            # se envía de verdad al confirmar.
            padre = _crear_salida(caja)
            sol.salidas.add(padre)
            for h in hijas:
                sol.salidas.add(_crear_salida(h))

            messages.success(
                request,
                f"Caja {caja.codigo_caja}" + (f" + {len(hijas)} tornillera(s)" if hijas else "")
                + " agregada al borrador. Revísala y confirma para surtir.")
            return redirect('admon_cirugias:solicitud_detalle', pk=pk)

        elif accion == 'editar':
            if sol.estado not in ('SOLICITADA', 'SURTIDA'):
                messages.error(request, "Ya no se puede editar (la cirugía está finalizada o liquidada).")
                return redirect('admon_cirugias:solicitud_detalle', pk=pk)
            sol.paciente = request.POST.get('paciente', '').strip()
            sol.doctor_id = request.POST.get('doctor') or None
            sol.hospital_id = request.POST.get('hospital') or None
            sol.fecha_cirugia = request.POST.get('fecha_cirugia') or None
            sol.cliente_id = request.POST.get('cliente') or None
            sol.comentario = request.POST.get('comentario', '')
            sol.save()
            # Sincroniza el snapshot de las salidas activas (aún no liquidadas).
            for s in sol.salidas.exclude(estado__in=('CANCELADA', 'CERRADA')):
                s.hospital_cliente = sol.hospital.nombre if sol.hospital else '—'
                s.doctor_responsable = sol.doctor.nombre if sol.doctor else None
                s.paciente_referencia = sol.paciente or None
                s.cliente = sol.cliente
                s.save(update_fields=['hospital_cliente', 'doctor_responsable',
                                      'paciente_referencia', 'cliente'])
            messages.success(request, f"Solicitud {sol.folio} actualizada.")
            return redirect('admon_cirugias:solicitud_detalle', pk=pk)

        elif accion == 'quitar_borrador':
            salida = get_object_or_404(sol.salidas.filter(estado='PREPARANDO'),
                                       id=request.POST.get('salida_id'))
            caja = salida.instancia_kit
            # Si es la caja de cirugía (padre), quita también sus tornilleras del borrador.
            hijas = sol.salidas.filter(estado='PREPARANDO', instancia_kit__caja_contenedora=caja)
            for hs in list(hijas):
                sol.salidas.remove(hs)
                hs.delete()
            sol.salidas.remove(salida)
            salida.delete()
            messages.info(request, f"Caja {caja.codigo_caja} quitada del borrador.")
            return redirect('admon_cirugias:solicitud_detalle', pk=pk)

        elif accion == 'enviar_borrador':
            borradores = list(sol.salidas.filter(estado='PREPARANDO')
                              .select_related('instancia_kit'))
            if not borradores:
                messages.error(request, "No hay cajas en borrador para surtir.")
                return redirect('admon_cirugias:solicitud_detalle', pk=pk)
            enviadas, fallidas = [], []
            for s in borradores:
                caja = s.instancia_kit
                # La caja de cirugía se permite vacía SOLO si alguna de sus
                # tornilleras del envío sí trae contenido; si todo está vacío,
                # se bloquea para no mandar una caja de cirugía en cero.
                hijas_borrador = [o for o in borradores
                                  if o.instancia_kit.caja_contenedora_id == caja.id]
                hijas_con_stock = any(h.instancia_kit.contenido().exists()
                                      for h in hijas_borrador)
                try:
                    enviar_caja_a_cirugia(salida=s, usuario=request.user,
                                          permitir_vacia=hijas_con_stock)
                    enviadas.append(caja.codigo_caja)
                except (ValueError, StockInsuficiente) as e:
                    fallidas.append(f"{caja.codigo_caja} ({e})")
            if enviadas and sol.estado == 'SOLICITADA':
                sol.estado = 'SURTIDA'
                sol.save(update_fields=['estado'])
            if enviadas:
                messages.success(
                    request, f"Surtido a la cirugía: {', '.join(enviadas)}."
                    + (f" No se pudieron enviar: {'; '.join(fallidas)}." if fallidas else ""))
            else:
                messages.error(request, f"No se pudo surtir. {'; '.join(fallidas)}")
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
