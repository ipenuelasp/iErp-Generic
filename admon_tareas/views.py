"""
Vistas del módulo de tareas (Fase 2): lista de tableros, vista Lista jerárquica
de un tablero y panel de detalle de tarea, con asignación + confirmación por
persona, comentarios, bitácora y adjuntos. Server-rendered, estilo del ERP.
"""
import hashlib
import os

from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse, Http404, FileResponse, JsonResponse
from django.utils import timezone

from admon_comunes.models import Adjunto
from .models import (Tablero, Tarea, Seccion, TareaAsignacion, TareaComentario,
                     TareaDependencia, TipoTablero, tipos_de)
from . import services


IMG_EXT = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg'}
MIME = {
    '.pdf': 'application/pdf', '.png': 'image/png', '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.webp': 'image/webp',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.csv': 'text/csv', '.zip': 'application/zip',
}


def _empresa(request):
    if not getattr(request, 'empresa', None):
        messages.warning(request, "No hay una empresa activa.")
        return None
    return request.empresa


def _usuarios_empresa(empresa):
    return User.objects.filter(perfil__empresas=empresa, is_active=True).distinct().order_by(
        'first_name', 'username')


def _puede_cerrar(user, tablero):
    """Quién puede aprobar/rechazar el cierre: el responsable del tablero, el
    dueño (OWNER) o un superusuario."""
    if user.is_superuser:
        return True
    perfil = getattr(user, 'perfil', None)
    if perfil and getattr(perfil, 'tipo_usuario', None) == 'OWNER':
        return True
    return tablero.responsable_id == user.id


def _fechas_desde_post(request):
    """Devuelve (inicio, fin, dias, horas). Si hay duración (días/horas) calcula
    la fecha fin en días hábiles; si no, respeta la fecha fin capturada."""
    import datetime

    def _d(s):
        s = (s or '').strip()
        try:
            return datetime.datetime.strptime(s, '%Y-%m-%d').date() if s else None
        except ValueError:
            return None

    ini = _d(request.POST.get('fecha_inicio_plan'))
    fin_manual = _d(request.POST.get('fecha_fin_plan'))
    try:
        dias = int(request.POST.get('duracion_dias') or 0)
    except ValueError:
        dias = 0
    try:
        horas = int(request.POST.get('duracion_horas') or 0)
    except ValueError:
        horas = 0
    fin = services.calcular_fin_plan(ini, dias, horas) or fin_manual
    return ini, fin, (dias or None), horas


def _guardar_adjunto(empresa, obj, archivo, usuario):
    data = archivo.read()
    archivo.seek(0)
    ext = os.path.splitext(archivo.name)[1].lower()[:12]
    ct = ContentType.objects.get_for_model(obj.__class__)
    return Adjunto.objects.create(
        empresa=empresa, content_type=ct, object_id=obj.pk,
        archivo=archivo, nombre_original=archivo.name[:255], extension=ext,
        mime_detectado=MIME.get(ext, getattr(archivo, 'content_type', '') or 'application/octet-stream'),
        tamano_bytes=len(data), hash_sha256=hashlib.sha256(data).hexdigest(),
        es_imagen=ext in IMG_EXT, estado_scan='PEND', subido_por=usuario)


class TablerosView(LoginRequiredMixin, View):
    template_name = 'admon_tareas/tableros.html'

    def get(self, request):
        empresa = _empresa(request)
        if not empresa:
            return redirect('home')
        tableros = list(Tablero.objects.operativos().filter(empresa=empresa)
                        .select_related('responsable'))
        for t in tableros:
            dets = list(t.tareas.all())
            hojas = [x for x in dets if not x.es_resumen and not x.es_bloqueante]
            t.n_tareas = len(hojas)
            t.n_comp = sum(1 for x in hojas if x.estado == 'COMP')
            t.n_bloq = sum(1 for x in dets if x.estado == 'BLOQ')
        plantillas = list(Tablero.objects.filter(empresa=empresa, es_plantilla=True, activo=True)
                          .order_by('nombre'))
        for p in plantillas:
            dets = list(p.tareas.all())
            p.n_tareas = sum(1 for x in dets if not x.es_resumen and not x.es_bloqueante)
            p.n_fases = sum(1 for x in dets if x.es_resumen)
        context = {
            'tableros': tableros,
            'plantillas': plantillas,
            'usuarios': _usuarios_empresa(empresa),
            'tipos': tipos_de(empresa),
            'tipos_todos': TipoTablero.objects.filter(empresa=empresa),
            'modos': Tablero.MODO_CIERRE,
            'seccion': 'tareas',
        }
        return render(request, self.template_name, context)

    def post(self, request):
        empresa = _empresa(request)
        if not empresa:
            return redirect('home')
        accion = request.POST.get('accion') or 'crear_tablero'

        if accion == 'crear_tipo':
            nombre = (request.POST.get('nombre') or '').strip()
            if nombre:
                orden = (TipoTablero.objects.filter(empresa=empresa).count())
                TipoTablero.objects.get_or_create(
                    empresa=empresa, nombre=nombre[:60], defaults={'orden': orden})
                messages.success(request, f"Tipo '{nombre}' agregado.")
            return redirect('admon_tareas:tableros')

        if accion == 'toggle_tipo':
            tp = TipoTablero.objects.filter(id=request.POST.get('tipo_id'), empresa=empresa).first()
            if tp:
                tp.activo = not tp.activo
                tp.save(update_fields=['activo'])
                messages.info(request, f"Tipo '{tp.nombre}' {'activado' if tp.activo else 'desactivado'}.")
            return redirect('admon_tareas:tableros')

        if accion == 'instanciar':
            plantilla = Tablero.objects.filter(
                id=request.POST.get('plantilla_id'), empresa=empresa, es_plantilla=True).first()
            nombre = (request.POST.get('nombre') or '').strip()
            if not plantilla or not nombre:
                messages.error(request, "Elige la plantilla y captura el nombre del tablero.")
                return redirect('admon_tareas:tableros')
            nuevo = services.instanciar_plantilla(
                plantilla, nombre=nombre,
                fecha_arranque=request.POST.get('fecha_arranque') or None,
                responsable_id=request.POST.get('responsable') or None,
                modo_cierre=request.POST.get('modo_cierre') or plantilla.modo_cierre,
                usuario=request.user)
            messages.success(request, f"Tablero {nuevo.codigo} creado desde la plantilla «{plantilla.nombre}». Asigna a las personas.")
            return redirect('admon_tareas:tablero_detalle', pk=nuevo.pk)

        nombre = (request.POST.get('nombre') or '').strip()
        if not nombre:
            messages.error(request, "Captura el nombre del tablero.")
            return redirect('admon_tareas:tableros')
        n = Tablero.objects.filter(empresa=empresa).count() + 1
        tipo = TipoTablero.objects.filter(id=request.POST.get('tipo'), empresa=empresa).first()
        tablero = Tablero.objects.create(
            empresa=empresa, codigo=(request.POST.get('codigo') or f'TAB-{n:04d}').strip()[:20],
            nombre=nombre, descripcion=(request.POST.get('descripcion') or '').strip(),
            tipo=tipo,
            modo_cierre=request.POST.get('modo_cierre') or 'TODOS',
            responsable_id=request.POST.get('responsable') or None,
            fecha_inicio=request.POST.get('fecha_inicio') or None,
            fecha_fin=request.POST.get('fecha_fin') or None,
            es_plantilla=bool(request.POST.get('es_plantilla')),
            creado_por=request.user)
        messages.success(request, f"Tablero {tablero.codigo} creado.")
        return redirect('admon_tareas:tablero_detalle', pk=tablero.pk)


class TableroDetalleView(LoginRequiredMixin, View):
    template_name = 'admon_tareas/tablero_detalle.html'

    def get(self, request, pk):
        empresa = _empresa(request)
        if not empresa:
            return redirect('home')
        tablero = get_object_or_404(Tablero, pk=pk, empresa=empresa)
        tareas = list(tablero.tareas.select_related('padre')
                      .prefetch_related('asignaciones__usuario')
                      .order_by('orden', 'ruta_wbs', 'id'))
        deps = (TareaDependencia.objects.filter(sucesora__tablero=tablero)
                .select_related('predecesora'))
        # Cada bloqueante se muestra debajo de la tarea que bloquea.
        bloqueante_de = {d.predecesora_id: d.sucesora_id for d in deps if d.origen == 'BLOQUEO'}
        ordenadas = _orden_jerarquico(tareas, bloqueante_de)
        # Marca las tareas bloqueadas por dependencias no cumplidas.
        espera = {}
        for d in deps:
            if services._bloquea(d):
                espera.setdefault(d.sucesora_id, []).append(
                    d.predecesora.ruta_wbs or d.predecesora.folio)
        for t in ordenadas:
            t.espera = espera.get(t.id)
        hojas = [t for t in tareas if not t.es_resumen and not t.es_bloqueante]
        resumen = {
            'total': len(hojas),
            'comp': sum(1 for t in hojas if t.estado == 'COMP'),
            'bloq': sum(1 for t in tareas if t.estado == 'BLOQ'),
            'avance': (sum(float(t.avance) for t in hojas) / len(hojas)) if hojas else 0,
        }
        gantt = _datos_gantt(ordenadas, tablero, list(deps))
        # Kanban: tareas hoja (no resumen) por estado
        estado_labels = dict(Tarea.ESTADO)
        kanban = [{'k': k, 'label': estado_labels[k],
                   'tareas': [t for t in ordenadas if not t.es_resumen and t.estado == k]}
                  for k in ('PEND', 'PROC', 'BLOQ', 'REVI', 'COMP')]
        context = {
            'tablero': tablero,
            'tareas': ordenadas,
            'resumen': resumen,
            'gantt': gantt,
            'kanban': kanban,
            'usuarios': _usuarios_empresa(empresa),
            'estados': Tarea.ESTADO,
            'prioridades': Tarea.PRIORIDAD,
            'roles': TareaAsignacion.ROL,
            'tipos_dep': TareaDependencia.TIPO,
            'seccion': 'tareas',
        }
        return render(request, self.template_name, context)

    def post(self, request, pk):
        empresa = _empresa(request)
        if not empresa:
            return redirect('home')
        from django.urls import reverse
        tablero = get_object_or_404(Tablero, pk=pk, empresa=empresa)
        accion = request.POST.get('accion')
        base_url = reverse('admon_tareas:tablero_detalle', kwargs={'pk': pk})

        def volver_a_tarea():
            tid = request.POST.get('tarea_id')
            return redirect(f"{base_url}?t={tid}" if tid else base_url)
        volver = volver_a_tarea()

        if accion == 'crear_tarea':
            titulo = (request.POST.get('titulo') or '').strip()
            if not titulo:
                messages.error(request, "La tarea necesita un título.")
                return volver
            padre = None
            if request.POST.get('padre'):
                padre = tablero.tareas.filter(id=request.POST.get('padre')).first()
            ini, fin, dias, horas = _fechas_desde_post(request)
            nueva = services.crear_tarea(
                tablero=tablero, usuario=request.user, titulo=titulo, padre=padre,
                prioridad=request.POST.get('prioridad') or 'MEDIA',
                fecha_inicio_plan=ini, fecha_fin_plan=fin,
                duracion_dias=dias, duracion_horas=horas,
                es_hito=bool(request.POST.get('es_hito')),
                perfil_sugerido=(request.POST.get('perfil_sugerido') or '').strip())
            # Dependencia opcional capturada al crear (agiliza el armado).
            pred = tablero.tareas.filter(id=request.POST.get('predecesora')).first() \
                if request.POST.get('predecesora') else None
            if pred and pred.id != nueva.id:
                tipo = request.POST.get('tipo_dep') or 'FS'
                if tipo not in dict(TareaDependencia.TIPO):
                    tipo = 'FS'
                try:
                    desfase = int(request.POST.get('desfase_dias') or 0)
                except ValueError:
                    desfase = 0
                if not services.crearia_ciclo(pred, nueva):
                    TareaDependencia.objects.create(
                        predecesora=pred, sucesora=nueva, tipo=tipo,
                        desfase_dias=desfase, origen='PLANEADA', creado_por=request.user)
                    services.agendar_desde_dependencias(nueva, request.user)
                    services.recalcular_tablero(tablero)
                    messages.success(request, f"Tarea agregada, depende de {pred.folio}.")
                else:
                    messages.warning(request, "Tarea agregada, pero la dependencia crearía un ciclo y se omitió.")
            else:
                messages.success(request, "Tarea agregada.")
            return volver

        # A partir de aquí, acciones sobre una tarea concreta
        tarea = get_object_or_404(tablero.tareas, id=request.POST.get('tarea_id')) \
            if request.POST.get('tarea_id') else None

        if accion == 'editar_tarea' and tarea:
            tarea.titulo = (request.POST.get('titulo') or tarea.titulo).strip()
            tarea.descripcion = request.POST.get('descripcion', tarea.descripcion)
            tarea.prioridad = request.POST.get('prioridad') or tarea.prioridad
            ini, fin, dias, horas = _fechas_desde_post(request)
            tarea.fecha_inicio_plan = ini
            tarea.fecha_fin_plan = fin
            tarea.duracion_dias = dias
            tarea.duracion_horas = horas
            if not tarea.es_resumen:
                try:
                    av = request.POST.get('avance')
                    if av not in (None, ''):
                        tarea.avance = max(0, min(100, float(av)))
                except ValueError:
                    pass
            tarea.save()
            movidas = services.reprogramar_cascada(tarea, request.user)
            services.recalcular_tablero(tablero)
            services.evaluar_cierre(tarea)
            services.registrar_actividad(tarea, request.user, 'EDITADA', detalle="Editó la tarea")
            if movidas:
                messages.info(request, f"Se recorrieron {len(movidas)} tarea(s) dependiente(s) en cascada.")
            messages.success(request, "Tarea actualizada.")

        elif accion == 'mover_tarea' and tarea:
            # Reprogramar desde el Gantt (arrastrar / redimensionar). Recibe las
            # fechas ya resueltas (ISO) que calculó el front desde los índices.
            import datetime as _dt

            def _pd(s):
                try:
                    return _dt.datetime.strptime((s or '').strip(), '%Y-%m-%d').date()
                except ValueError:
                    return None
            ini = _pd(request.POST.get('inicio'))
            fin = _pd(request.POST.get('fin'))
            es_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            if not ini:
                if es_ajax:
                    return JsonResponse({'ok': False, 'error': 'fecha inválida'}, status=400)
                return volver
            if not fin or fin < ini:
                fin = ini
            tarea.fecha_inicio_plan = ini
            tarea.fecha_fin_plan = ini if tarea.es_hito else fin
            tarea.duracion_dias = services.dias_habiles_entre(ini, tarea.fecha_fin_plan)
            tarea.save(update_fields=['fecha_inicio_plan', 'fecha_fin_plan', 'duracion_dias'])
            services.registrar_actividad(
                tarea, request.user, 'FECHA',
                detalle=f"Reprogramó en el cronograma: {ini:%d/%m} – {tarea.fecha_fin_plan:%d/%m}")
            movidas = services.reprogramar_cascada(tarea, request.user)
            services.recalcular_tablero(tablero)
            if movidas:
                messages.info(request, f"Se recorrieron {len(movidas)} tarea(s) dependiente(s) en cascada.")
            if es_ajax:
                return JsonResponse({'ok': True, 'cascada': len(movidas)})
            return volver

        elif accion == 'eliminar_tarea' and tarea:
            folio = tarea.folio
            tarea.delete()  # CASCADE en Python borra hijos/asignaciones/etc.
            services.recalcular_tablero(tablero)
            messages.info(request, f"Tarea {folio} eliminada.")
            return redirect(base_url)

        elif accion == 'bloquear_tarea' and tarea:
            if tarea.estado in ('BLOQ', 'COMP', 'CANC'):
                messages.error(request, "Esta tarea no se puede bloquear en su estado actual.")
                return volver
            motivo = (request.POST.get('motivo') or '').strip()
            titulo = (request.POST.get('titulo_bloqueante') or '').strip()
            if not motivo or not titulo:
                messages.error(request, "El motivo y el título de la tarea que la desbloquea son obligatorios.")
                return volver
            asignados = [u for u in request.POST.getlist('asignados')
                         if _usuarios_empresa(empresa).filter(id=u).exists()]
            import datetime as _dt
            try:
                fecha = _dt.datetime.strptime(
                    (request.POST.get('fecha_compromiso') or '').strip(), '%Y-%m-%d').date()
            except ValueError:
                fecha = None
            bloqueante = services.bloquear(
                tarea=tarea, usuario=request.user, motivo=motivo, titulo=titulo,
                asignados_ids=asignados, fecha_compromiso=fecha)
            messages.warning(request, f"Tarea bloqueada. Se creó {bloqueante.folio} para desbloquearla.")
            return volver

        elif accion == 'cambiar_estado' and tarea:
            nuevo = request.POST.get('estado')
            if nuevo == 'BLOQ':
                messages.error(request, "Para bloquear usa «Bloquear tarea»: exige motivo y la tarea que la desbloquea.")
                return volver
            if nuevo in ('PROC', 'REVI', 'COMP') and services.bloqueada_por(tarea):
                bloq = services.bloqueada_por(tarea)
                nombres = ", ".join(f"{d.predecesora.ruta_wbs or d.predecesora.folio}" for d in bloq)
                messages.error(request, f"No puede avanzar: espera a {nombres}.")
                return volver
            if nuevo in dict(Tarea.ESTADO):
                ant = tarea.estado
                tarea.estado = nuevo
                campos = ['estado', 'cerrado_en', 'cerrado_por', 'avance', 'fecha_fin_real']
                if nuevo == 'COMP':
                    tarea.cerrado_en = timezone.now()
                    tarea.cerrado_por = request.user
                    tarea.fecha_fin_real = timezone.localdate()
                    if not tarea.es_resumen:
                        tarea.avance = 100
                elif ant == 'COMP':
                    # Se reabre: se limpia el cierre real
                    tarea.cerrado_en = None
                    tarea.cerrado_por = None
                    tarea.fecha_fin_real = None
                tarea.save(update_fields=campos)
                if nuevo == 'COMP':
                    services.resolver_bloqueos_de(tarea, request.user)
                services.recalcular_tablero(tablero)
                services.registrar_actividad(tarea, request.user, 'ESTADO',
                                             campo='estado', valor_ant=ant, valor_nue=nuevo)
                messages.success(request, "Estado actualizado.")

        elif accion == 'aprobar_tarea' and tarea:
            if not _puede_cerrar(request.user, tablero):
                messages.error(request, "Solo el responsable del tablero puede aprobar el cierre.")
            elif tarea.estado != 'REVI':
                messages.error(request, "La tarea no está en revisión.")
            else:
                tarea.estado = 'COMP'
                tarea.cerrado_en = timezone.now()
                tarea.cerrado_por = request.user
                tarea.fecha_fin_real = timezone.localdate()
                if not tarea.es_resumen:
                    tarea.avance = 100
                tarea.save(update_fields=['estado', 'cerrado_en', 'cerrado_por',
                                          'fecha_fin_real', 'avance'])
                desb = services.resolver_bloqueos_de(tarea, request.user)
                services.recalcular_tablero(tablero)
                services.registrar_actividad(tarea, request.user, 'APROBO',
                                             detalle="Aprobó y completó la tarea")
                msg = f"{tarea.folio} aprobada y completada."
                if desb:
                    msg += f" Se desbloqueó {len(desb)} tarea(s)."
                messages.success(request, msg)

        elif accion == 'rechazar_tarea' and tarea:
            motivo = (request.POST.get('motivo') or '').strip()
            if not _puede_cerrar(request.user, tablero):
                messages.error(request, "Solo el responsable del tablero puede rechazar.")
            elif tarea.estado != 'REVI':
                messages.error(request, "La tarea no está en revisión.")
            elif not motivo:
                messages.error(request, "Escribe el motivo del rechazo para regresarla.")
            else:
                tarea.estado = 'PROC'
                tarea.save(update_fields=['estado'])
                # Se limpian las confirmaciones: los asignados deben volver a confirmar.
                tarea.asignaciones.update(completado=False, completado_en=None)
                services.registrar_actividad(
                    tarea, request.user, 'RECHAZO',
                    detalle=f"Regresó a proceso · Motivo: {motivo}")
                messages.info(request, "Tarea regresada a proceso. Se avisó el motivo en la bitácora.")

        elif accion == 'asignar' and tarea:
            uid = request.POST.get('usuario')
            if uid and _usuarios_empresa(empresa).filter(id=uid).exists():
                obj, creada = TareaAsignacion.objects.get_or_create(
                    tarea=tarea, usuario_id=uid,
                    defaults={'rol': request.POST.get('rol') or 'COLA',
                              'asignado_por': request.user})
                if creada:
                    services.registrar_actividad(tarea, request.user, 'ASIGNO',
                                                 detalle=f"Asignó a {obj.usuario}")
                    if tarea.estado == 'PEND':
                        tarea.estado = 'PROC'
                        tarea.save(update_fields=['estado'])
                messages.success(request, "Persona asignada.")

        elif accion == 'quitar_asignacion' and tarea:
            TareaAsignacion.objects.filter(tarea=tarea, id=request.POST.get('asignacion_id')).delete()
            services.evaluar_cierre(tarea)
            messages.info(request, "Asignación quitada.")

        elif accion == 'agregar_dependencia' and tarea:
            pred = tablero.tareas.filter(id=request.POST.get('predecesora')).first()
            tipo = request.POST.get('tipo_dep') or 'FS'
            if tipo not in dict(TareaDependencia.TIPO):
                tipo = 'FS'
            try:
                desfase = int(request.POST.get('desfase_dias') or 0)
            except ValueError:
                desfase = 0
            existente = TareaDependencia.objects.filter(predecesora=pred, sucesora=tarea).first() if pred else None
            if not pred or pred.id == tarea.id:
                messages.error(request, "Elige una tarea válida.")
            elif not existente and services.crearia_ciclo(pred, tarea):
                messages.error(request, "No se puede: crearía un ciclo de dependencias.")
            else:
                if existente:
                    existente.tipo = tipo
                    existente.desfase_dias = desfase
                    existente.save(update_fields=['tipo', 'desfase_dias'])
                    msg = "Dependencia actualizada."
                else:
                    TareaDependencia.objects.create(
                        predecesora=pred, sucesora=tarea, tipo=tipo,
                        desfase_dias=desfase, origen='PLANEADA', creado_por=request.user)
                    msg = "Dependencia agregada."
                lag_txt = (f" {'+' if desfase > 0 else ''}{desfase}d" if desfase else "")
                services.registrar_actividad(
                    tarea, request.user, 'DEPENDENCIA',
                    detalle=f"Depende de {pred.folio} · {pred.titulo} ({tipo}{lag_txt})")
                # Agenda la tarea justo después de su predecesora (y recorre su cadena).
                services.agendar_desde_dependencias(tarea, request.user)
                services.recalcular_tablero(tablero)
                messages.success(request, msg)

        elif accion == 'quitar_dependencia' and tarea:
            TareaDependencia.objects.filter(
                id=request.POST.get('dep_id'), sucesora=tarea).delete()
            messages.info(request, "Dependencia quitada.")

        elif accion == 'confirmar' and tarea:
            asig = TareaAsignacion.objects.filter(
                tarea=tarea, usuario=request.user).first()
            bloq = services.bloqueada_por(tarea)
            if bloq:
                nombres = ", ".join(f"{d.predecesora.ruta_wbs or d.predecesora.folio}" for d in bloq)
                messages.error(request, f"No puedes confirmar todavía: esta tarea espera a {nombres}.")
            elif not asig:
                messages.error(request, "No estás asignado a esta tarea.")
            else:
                services.confirmar_asignacion(
                    asig, request.user, completado=not asig.completado,
                    nota=request.POST.get('nota', ''))
                messages.success(request, "Confirmación registrada.")

        elif accion == 'comentar' and tarea:
            texto = (request.POST.get('texto') or '').strip()
            if texto:
                com = TareaComentario.objects.create(tarea=tarea, autor=request.user, texto=texto)
                for f in request.FILES.getlist('archivos'):
                    _guardar_adjunto(empresa, com, f, request.user)
                services.registrar_actividad(tarea, request.user, 'COMENTO', detalle="Comentó")
                messages.success(request, "Comentario agregado.")

        elif accion == 'subir_adjunto' and tarea:
            n = 0
            for f in request.FILES.getlist('archivos'):
                _guardar_adjunto(empresa, tarea, f, request.user)
                n += 1
            if n:
                services.registrar_actividad(tarea, request.user, 'ADJUNTO',
                                             detalle=f"Adjuntó {n} archivo(s)")
                messages.success(request, f"{n} archivo(s) adjuntado(s).")

        elif accion == 'eliminar_adjunto' and tarea:
            Adjunto.objects.filter(
                id=request.POST.get('adjunto_id'), empresa=empresa,
                content_type=ContentType.objects.get_for_model(Tarea),
                object_id=tarea.id).delete()
            messages.info(request, "Adjunto eliminado.")
        else:
            if accion != 'crear_tarea':
                messages.error(request, "Acción no válida.")
        return volver


class TareaPanelView(LoginRequiredMixin, View):
    """Devuelve el HTML del panel de detalle de una tarea (para el drawer)."""
    template_name = 'admon_tareas/_tarea_panel.html'

    def get(self, request, pk):
        empresa = _empresa(request)
        if not empresa:
            return HttpResponse(status=403)
        tarea = get_object_or_404(
            Tarea.objects.select_related('tablero', 'padre'), pk=pk, empresa=empresa)
        subtareas = list(tarea.hijos.exclude(es_bloqueante=True)
                         .prefetch_related('asignaciones__usuario').order_by('orden', 'ruta_wbs'))
        ct = ContentType.objects.get_for_model(Tarea)
        adjuntos = Adjunto.objects.filter(content_type=ct, object_id=tarea.id)
        todas_deps = list(TareaDependencia.objects.filter(sucesora=tarea)
                          .select_related('predecesora'))
        dependencias = [d for d in todas_deps if d.origen == 'PLANEADA']
        # Candidatas a predecesora: otras tareas del tablero (no la misma).
        candidatas = (tarea.tablero.tareas.exclude(id=tarea.id)
                      .order_by('orden', 'ruta_wbs').values('id', 'folio', 'ruta_wbs', 'titulo'))
        context = {
            'tablero': tarea.tablero,
            't': tarea,
            'asignaciones': tarea.asignaciones.select_related('usuario').all(),
            'subtareas': subtareas,
            'comentarios': tarea.comentarios.select_related('autor').prefetch_related('adjuntos'),
            'actividad': tarea.actividad.select_related('usuario')[:30],
            'adjuntos': adjuntos,
            'usuarios': _usuarios_empresa(empresa),
            'roles': TareaAsignacion.ROL,
            'estados': Tarea.ESTADO,
            'mi_asignacion': tarea.asignaciones.filter(usuario=request.user).first(),
            'puede_cerrar': _puede_cerrar(request.user, tarea.tablero),
            'dependencias': dependencias,
            'candidatas': candidatas,
            'tipos_dep': TareaDependencia.TIPO,
            # "Espera por cronograma": solo dependencias PLANEADA no cumplidas.
            'espera_dep': [d for d in dependencias if services._bloquea(d)],
            # Bloqueo formal: tareas bloqueantes (origen BLOQUEO).
            'bloqueos': [d for d in todas_deps if d.origen == 'BLOQUEO'],
            'puede_bloquear': tarea.estado not in ('BLOQ', 'COMP', 'CANC') and not tarea.es_bloqueante,
        }
        return render(request, self.template_name, context)


class AdjuntoDescargaView(LoginRequiredMixin, View):
    def get(self, request, pk):
        empresa = _empresa(request)
        if not empresa:
            return HttpResponse(status=403)
        adj = get_object_or_404(Adjunto, pk=pk, empresa=empresa)
        try:
            return FileResponse(adj.archivo.open('rb'), as_attachment=True,
                                filename=adj.nombre_original)
        except FileNotFoundError:
            raise Http404


def _datos_gantt(ordenadas, tablero, deps):
    """Calcula el calendario de días hábiles y la posición (px) de cada barra,
    hitos, línea de hoy y segmentos de dependencia para el cronograma.
    Atributos que deja en cada tarea: gx, gw, grow, gvis (si tiene barra)."""
    import datetime as _dt
    CW, ROWH, BAR_TOP, BAR_H = 28, 34, 9, 16

    fechas = []
    for t in ordenadas:
        if t.fecha_inicio_plan:
            fechas.append(t.fecha_inicio_plan)
        if t.fecha_fin_plan:
            fechas.append(t.fecha_fin_plan)
    if tablero.fecha_inicio:
        fechas.append(tablero.fecha_inicio)
    if tablero.fecha_fin:
        fechas.append(tablero.fecha_fin)

    hoy = timezone.localdate()
    if fechas:
        inicio, fin = min(fechas), max(fechas)
    else:
        inicio, fin = hoy, hoy + _dt.timedelta(days=27)
    inicio = min(inicio, hoy)
    fin = max(fin, hoy)
    # límite de seguridad para no generar un Gantt gigante
    if (fin - inicio).days > 260:
        fin = inicio + _dt.timedelta(days=260)

    meses = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']
    dias, idx_map = [], {}
    d = inicio
    while d <= fin:
        if d.weekday() < 5:   # lun-vie
            idx_map[d] = len(dias)
            dias.append({'num': d.day, 'mes': meses[d.month - 1],
                         'week_start': d.weekday() == 0, 'fecha': d.isoformat()})
        d += _dt.timedelta(days=1)
    if not dias:   # por si acaso
        dias = [{'num': hoy.day, 'mes': meses[hoy.month - 1], 'week_start': True}]

    def idx_de(f):
        if not f:
            return None
        x = max(inicio, min(f, fin))
        while x.weekday() >= 5 and x < fin:
            x += _dt.timedelta(days=1)
        return idx_map.get(x)

    # Span propio (por fechas) de cada tarea, en índices de día.
    propio = {}
    for t in ordenadas:
        si = idx_de(t.fecha_inicio_plan)
        ei = idx_de(t.fecha_fin_plan) if not t.es_hito else si
        # Una tarea bloqueante sin fecha compromiso se muestra como punto (rombo)
        # en su inicio, para que aparezca en el cronograma.
        t.gbloq_punto = t.es_bloqueante and not t.fecha_fin_plan
        if t.gbloq_punto and si is not None:
            ei = si
        propio[t.id] = (si, ei)

    # Hijos por padre (las bloqueantes viven fuera de la jerarquía).
    hijos_de = {}
    for t in ordenadas:
        if t.padre_id and not t.es_bloqueante:
            hijos_de.setdefault(t.padre_id, []).append(t)

    # Span efectivo: una FASE (resumen) abarca de la primera a la última de sus
    # subtareas; recursivo. Una hoja usa sus propias fechas.
    span = {}

    def _span(t):
        if t.id in span:
            return span[t.id]
        if t.es_resumen and hijos_de.get(t.id):
            partes = [p for p in (_span(h) for h in hijos_de[t.id]) if p]
            if partes:
                span[t.id] = (min(p[0] for p in partes), max(p[1] for p in partes))
                return span[t.id]
        si, ei = propio[t.id]
        span[t.id] = (si, ei) if (si is not None and ei is not None) else None
        return span[t.id]

    fila = {}
    for row, t in enumerate(ordenadas):
        t.grow = row
        t.gy = row * ROWH + BAR_TOP
        sp = _span(t)
        if sp:
            si, ei = sp
            if ei < si:
                ei = si
            t.gvis = True
            t.gx = si * CW
            t.gw = (ei - si + 1) * CW
            t.gmid = si * CW + CW / 2   # centro (para el hito)
            fila[t.id] = (si, ei, row)
        else:
            t.gvis = False

    # Segmentos de dependencia (predecesora fin → sucesora inicio)
    segmentos = []
    for dep in deps:
        p = fila.get(dep.predecesora_id)
        s = fila.get(dep.sucesora_id)
        if not p or not s:
            continue
        x1 = (p[1] + 1) * CW
        y1 = p[2] * ROWH + ROWH / 2
        x2 = s[0] * CW
        y2 = s[2] * ROWH + ROWH / 2
        segmentos.append({'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2})

    hoy_idx = idx_map.get(hoy)
    if hoy_idx is None:   # si hoy cae en finde, usa el hábil más cercano
        h = hoy
        while h.weekday() >= 5 and h < fin:
            h += _dt.timedelta(days=1)
        hoy_idx = idx_map.get(h)

    # Semanas (para el encabezado)
    semanas = []
    i = 0
    while i < len(dias):
        semanas.append({'label': f"{dias[i]['num']} {dias[i]['mes']}",
                        'ancho': min(5, len(dias) - i) * CW})
        i += 5

    return {
        'dias': dias, 'semanas': semanas, 'cw': CW, 'rowh': ROWH,
        'bar_top': BAR_TOP, 'bar_h': BAR_H,
        'ancho': len(dias) * CW, 'alto': len(ordenadas) * ROWH,
        'hoy_x': (hoy_idx * CW + CW / 2) if hoy_idx is not None else None,
        'segmentos': segmentos,
    }


def _orden_jerarquico(tareas, bloqueante_de=None):
    """Ordena las tareas para la Lista: cada raíz seguida de su subárbol (por
    orden/WBS). Cada tarea bloqueante se coloca justo DEBAJO de la tarea que
    bloquea (sin ser su hija). `bloqueante_de`: {id_bloqueante: id_bloqueada}."""
    bloqueante_de = bloqueante_de or {}
    por_padre = {}
    for t in tareas:
        por_padre.setdefault(t.padre_id, []).append(t)
    for hijos in por_padre.values():
        hijos.sort(key=lambda x: (x.orden, x.id))
    salida = []

    def _walk(padre_id):
        for t in por_padre.get(padre_id, []):
            if t.es_bloqueante:
                continue
            salida.append(t)
            _walk(t.id)

    _walk(None)

    # Inserta las bloqueantes debajo de la tarea que bloquean.
    bloqueantes = [t for t in tareas if t.es_bloqueante]
    por_bloqueada = {}
    for b in bloqueantes:
        por_bloqueada.setdefault(bloqueante_de.get(b.id), []).append(b)
    resultado, colocadas = [], set()
    for t in salida:
        resultado.append(t)
        for b in por_bloqueada.get(t.id, []):
            resultado.append(b)
            colocadas.add(b.id)
    for b in bloqueantes:            # bloqueadas ausentes → al final
        if b.id not in colocadas:
            resultado.append(b)
    return resultado
