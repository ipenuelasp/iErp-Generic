import decimal
from datetime import datetime

from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.db.models import Sum

from admon_empresas.models import Moneda
from admon_inventarios.models import InstanciaKit, SalidaKit, Producto, Existencia
from admon_inventarios.services import (registrar_retorno_kit, StockInsuficiente,
                                        enviar_caja_a_cirugia, surtir_material_suelto)
from admon_ventas.models import Cliente
from .models import Doctor, Hospital, SolicitudCirugia, SueltoCirugia
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
        pid = s.instancia_kit.caja_contenedora_id if s.instancia_kit_id else None
        padre = por_box.get(pid) if pid else None
        if padre and padre is not s:
            padre.hijas_salidas.append(s)
        else:
            raiz.append(s)
    return raiz


class ExistenciasSueltoView(LoginRequiredMixin, View):
    """Devuelve (JSON) las existencias de un producto en el stock general de la
    sucursal, para elegir qué serie / lote mandar como material suelto."""
    def get(self, request, pk):
        from django.http import JsonResponse
        ctx = _ctx(request)
        if not ctx:
            return JsonResponse({'error': 'sin contexto'}, status=400)
        empresa, sucursal = ctx
        prod = Producto.objects.filter(id=request.GET.get('producto'), empresa=empresa).first()
        if not prod:
            return JsonResponse({'error': 'producto no encontrado'}, status=404)

        exs = list(Existencia.objects
                   .filter(producto=prod, sucursal=sucursal, cantidad__gt=0)
                   .exclude(ubicacion__almacen__codigo='CAJAS')
                   .select_related('ubicacion', 'lote', 'serie')
                   .order_by('lote__fecha_caducidad', 'id'))
        total = sum((e.cantidad for e in exs), decimal.Decimal('0'))

        if prod.es_serializable:
            tipo = 'serie'
            opciones = [{
                'serie_id': e.serie_id, 'serie': e.serie.serie if e.serie else '—',
                'ubicacion_id': e.ubicacion_id, 'ubicacion': str(e.ubicacion),
            } for e in exs if e.serie_id]
        elif prod.es_loteable:
            tipo = 'lote'
            opciones = [{
                'lote_id': e.lote_id,
                'numero_lote': e.lote.numero_lote if e.lote else 's/lote',
                'caducidad': e.lote.fecha_caducidad.strftime('%d/%m/%Y') if e.lote and e.lote.fecha_caducidad else '',
                'ubicacion_id': e.ubicacion_id, 'ubicacion': str(e.ubicacion),
                'disp': _fmt_cant(e.cantidad),
            } for e in exs]
        else:
            tipo = 'simple'
            opciones = []
        return JsonResponse({'tipo': tipo, 'total': _fmt_cant(total), 'opciones': opciones})


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

        # Auto-corrige el estado según las salidas activas.
        if sol.estado in ('SURTIDA', 'ENVIADA', 'RETORNADA'):
            activas = [s for s in salidas if s.estado != 'CANCELADA']
            if not activas:
                # Se quitó/canceló toda salida: vuelve a "Solicitada".
                if sol.estado != 'SOLICITADA':
                    sol.estado = 'SOLICITADA'
                    sol.save(update_fields=['estado'])
            elif all(s.estado == 'RETORNADA' for s in activas) and sol.estado == 'SURTIDA':
                # Todo regresó: pasa a "Regresada (pendiente de finalizar)".
                sol.estado = 'RETORNADA'
                sol.save(update_fields=['estado'])
            elif any(s.estado in ('ENVIADA', 'EN_USO') for s in activas) and sol.estado == 'RETORNADA':
                # Se surtió una caja nueva después: regresa a "Surtida".
                sol.estado = 'SURTIDA'
                sol.save(update_fields=['estado'])

        hay_retornadas = any(s.estado == 'RETORNADA' for s in salidas)

        # Separa borradores (por surtir) de las ya enviadas/en proceso.
        borradores = [s for s in salidas if s.estado == 'PREPARANDO']
        enviadas = [s for s in salidas if s.estado not in ('PREPARANDO', 'CANCELADA')]

        # El material suelto (salida sin caja) se maneja aparte del árbol de cajas.
        enviadas_cajas = [s for s in enviadas if s.instancia_kit_id]
        sueltos_enviados = [s for s in enviadas if not s.instancia_kit_id]

        # Borrador: adjunta el resumen del contenido actual + completitud.
        for s in borradores:
            s.resumen = _resumen_caja(s.instancia_kit)
        # Enviadas: adjunta el resumen de lo que salió (encabezado→detalle).
        for s in enviadas:
            s.items_enviados = _items_enviados(s)

        borradores_arbol = _arbol_salidas(borradores)
        enviadas_arbol = _arbol_salidas(enviadas_cajas)

        # Cajas disponibles para surtir: de nivel superior (no anidadas), que no
        # estén ya en esta cirugía. Incluye cajas con plantilla y armadas libres.
        ya_en_sol = {s.instancia_kit_id for s in salidas if s.estado != 'CANCELADA'}
        cajas_disponibles = InstanciaKit.objects.filter(
            sucursal_actual=sucursal, estado='DISPONIBLE', caja_contenedora__isnull=True
        ).exclude(id__in=ya_en_sol).select_related('kit').prefetch_related('cajas_hijas')

        # Selector visual: cada caja con su contenido, completitud y tornilleras.
        # Ya no se puede surtir cuando todo lo enviado ya regresó y no quedan
        # borradores pendientes (la cirugía está lista para finalizar).
        puede_surtir = sol.estado in ('SOLICITADA', 'SURTIDA')
        hay_sueltos_plan = sol.sueltos.exists()
        if (enviadas and all(s.estado == 'RETORNADA' for s in enviadas)
                and not borradores and not hay_sueltos_plan):
            puede_surtir = False
        cajas_surtir = []
        if puede_surtir:
            for c in cajas_disponibles:
                info = _resumen_caja(c)
                info['tornilleras'] = [
                    _resumen_caja(h) for h in c.cajas_hijas.filter(estado='DISPONIBLE')]
                cajas_surtir.append(info)

        # ----- Material suelto (productos individuales, fuera de caja) -----
        sueltos_borrador = list(sol.sueltos.select_related('producto', 'serie', 'lote', 'ubicacion'))
        # Existencia disponible de cada línea (según su serie/lote/ubicación elegida)
        # para avisar en el borrador si se pide más de lo que hay.
        hay_falta_suelto = False
        for x in sueltos_borrador:
            base = (Existencia.objects
                    .filter(producto=x.producto, sucursal=sucursal, cantidad__gt=0)
                    .exclude(ubicacion__almacen__codigo='CAJAS'))
            if x.serie_id:
                base = base.filter(serie_id=x.serie_id)
            elif x.lote_id:
                base = base.filter(lote_id=x.lote_id)
                if x.ubicacion_id:
                    base = base.filter(ubicacion_id=x.ubicacion_id)
            disp = base.aggregate(t=Sum('cantidad'))['t'] or decimal.Decimal('0')
            falta = x.cantidad - disp
            x.disp = _fmt_cant(disp)
            x.falta = _fmt_cant(falta) if falta > 0 else None
            if falta > 0:
                hay_falta_suelto = True
        for s in sueltos_enviados:
            s.items_enviados = _items_enviados(s)
        # Productos que hoy tienen existencia en el stock general de la sucursal
        # (excluye el almacén de CAJAS): son los que se pueden surtir sueltos.
        productos_suelto = []
        if puede_surtir:
            disp = (Existencia.objects
                    .filter(sucursal=sucursal, cantidad__gt=0, producto__empresa=empresa)
                    .exclude(ubicacion__almacen__codigo='CAJAS')
                    .values('producto_id')
                    .annotate(total=Sum('cantidad')))
            tot_por_prod = {d['producto_id']: d['total'] for d in disp}
            if tot_por_prod:
                prods = Producto.objects.filter(id__in=tot_por_prod.keys()).order_by('sku')
                productos_suelto = [
                    {'id': p.id, 'sku': p.sku, 'nombre': p.nombre,
                     'stock': _fmt_cant(tot_por_prod.get(p.id, 0))}
                    for p in prods]

        # La solicitud se puede editar mientras no esté finalizada/liquidada.
        puede_editar = sol.estado in ('SOLICITADA', 'SURTIDA', 'RETORNADA')
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
            'sueltos_borrador': sueltos_borrador,
            'sueltos_enviados': sueltos_enviados,
            'hay_falta_suelto': hay_falta_suelto,
            'productos_suelto': productos_suelto,
            'hay_borradores': bool(borradores) or bool(sueltos_borrador),
            'hay_retornadas': hay_retornadas,
            'cajas_surtir': cajas_surtir,
            'puede_surtir': puede_surtir,
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

        elif accion == 'agregar_suelto':
            # Agrega un producto individual (fuera de caja) al borrador de surtido.
            # Serializado → se elige la(s) serie(s) exacta(s). Loteable → se indica el
            # lote a sacar (el más viejo por defecto). Simple → solo cantidad (FIFO).
            if sol.estado not in ('SOLICITADA', 'SURTIDA'):
                messages.error(request, "Ya no se puede agregar material a esta cirugía.")
                return redirect('admon_cirugias:solicitud_detalle', pk=pk)
            prod = Producto.objects.filter(id=request.POST.get('producto'), empresa=empresa).first()
            if not prod:
                messages.error(request, "Selecciona un producto.")
                return redirect('admon_cirugias:solicitud_detalle', pk=pk)

            def _par(valor):
                # "serie_o_lote_id:ubicacion_id" → (int, int)
                a, _, b = (valor or '').partition(':')
                return (int(a) if a else None, int(b) if b else None)

            agregados = 0
            if prod.es_serializable:
                seleccion = request.POST.getlist('serie_sel')
                if not seleccion:
                    messages.error(request, "Elige al menos una serie a enviar.")
                    return redirect('admon_cirugias:solicitud_detalle', pk=pk)
                for val in seleccion:
                    serie_id, ubic_id = _par(val)
                    if not serie_id:
                        continue
                    if sol.sueltos.filter(serie_id=serie_id).exists():
                        continue  # ya estaba en el borrador
                    SueltoCirugia.objects.create(
                        solicitud=sol, producto=prod, cantidad=decimal.Decimal('1'),
                        serie_id=serie_id, ubicacion_id=ubic_id, creado_por=request.user)
                    agregados += 1
                messages.success(request, f"{agregados} serie(s) de {prod.sku} agregada(s) al borrador.")

            elif prod.es_loteable:
                lote_id, ubic_id = _par(request.POST.get('lote_sel'))
                try:
                    cant = decimal.Decimal(request.POST.get('cantidad') or '0')
                except decimal.InvalidOperation:
                    cant = decimal.Decimal('0')
                if not lote_id or cant <= 0:
                    messages.error(request, "Elige el lote y una cantidad mayor a 0.")
                    return redirect('admon_cirugias:solicitud_detalle', pk=pk)
                existente = sol.sueltos.filter(producto=prod, lote_id=lote_id, ubicacion_id=ubic_id).first()
                if existente:
                    existente.cantidad += cant
                    existente.save(update_fields=['cantidad'])
                else:
                    SueltoCirugia.objects.create(
                        solicitud=sol, producto=prod, cantidad=cant,
                        lote_id=lote_id, ubicacion_id=ubic_id, creado_por=request.user)
                messages.success(request, f"Agregado al borrador: {prod.sku} x{_fmt_cant(cant)} (lote indicado).")

            else:
                try:
                    cant = decimal.Decimal(request.POST.get('cantidad') or '0')
                except decimal.InvalidOperation:
                    cant = decimal.Decimal('0')
                if cant <= 0:
                    messages.error(request, "Captura una cantidad mayor a 0.")
                    return redirect('admon_cirugias:solicitud_detalle', pk=pk)
                existente = sol.sueltos.filter(producto=prod, serie__isnull=True, lote__isnull=True).first()
                if existente:
                    existente.cantidad += cant
                    existente.save(update_fields=['cantidad'])
                else:
                    SueltoCirugia.objects.create(
                        solicitud=sol, producto=prod, cantidad=cant, creado_por=request.user)
                messages.success(request, f"Agregado al borrador: {prod.sku} x{_fmt_cant(cant)}.")
            return redirect('admon_cirugias:solicitud_detalle', pk=pk)

        elif accion == 'quitar_suelto':
            sol.sueltos.filter(id=request.POST.get('suelto_id')).delete()
            messages.info(request, "Producto suelto quitado del borrador.")
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
            sueltos_plan = list(sol.sueltos.select_related('producto', 'serie', 'lote', 'ubicacion'))
            if not borradores and not sueltos_plan:
                messages.error(request, "No hay material en borrador para surtir.")
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

            # Material suelto: una sola salida sin caja con todos los productos
            # individuales, descontados del stock general de la sucursal.
            if sueltos_plan:
                salida_suelto = SalidaKit.objects.create(
                    empresa=empresa, instancia_kit=None, sucursal_origen=sucursal,
                    hospital_cliente=sol.hospital.nombre if sol.hospital else '—',
                    doctor_responsable=sol.doctor.nombre if sol.doctor else None,
                    numero_cirugia=sol.folio, paciente_referencia=sol.paciente or None,
                    cliente=sol.cliente, creado_por=request.user,
                    notas=f"Material suelto · Cirugía {sol.folio}")
                try:
                    surtir_material_suelto(
                        salida=salida_suelto, planes=sueltos_plan, usuario=request.user)
                    sol.salidas.add(salida_suelto)
                    sol.sueltos.all().delete()
                    enviadas.append(f"Material suelto ({len(sueltos_plan)} producto/s)")
                except (ValueError, StockInsuficiente) as e:
                    salida_suelto.delete()
                    fallidas.append(f"Material suelto ({e})")

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
        # Si ya regresó TODO el material enviado, la cirugía pasa a "Regresada
        # (pendiente de finalizar)" para avisar que está lista para cerrarse.
        activas = [s for s in sol.salidas.exclude(estado='CANCELADA')]
        if activas and all(s.estado == 'RETORNADA' for s in activas) and sol.estado == 'SURTIDA':
            sol.estado = 'RETORNADA'
            sol.save(update_fields=['estado'])
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
