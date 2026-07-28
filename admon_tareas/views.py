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
from django.http import HttpResponse, Http404, FileResponse
from django.utils import timezone

from admon_comunes.models import Adjunto
from .models import (Tablero, Tarea, Seccion, TareaAsignacion, TareaComentario,
                     TipoTablero, tipos_de)
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
        context = {
            'tableros': tableros,
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
        # Orden jerárquico para la Lista: raíces por orden, luego sus hijos (WBS).
        ordenadas = _orden_jerarquico(tareas)
        hojas = [t for t in tareas if not t.es_resumen and not t.es_bloqueante]
        resumen = {
            'total': len(hojas),
            'comp': sum(1 for t in hojas if t.estado == 'COMP'),
            'bloq': sum(1 for t in tareas if t.estado == 'BLOQ'),
            'avance': (sum(float(t.avance) for t in hojas) / len(hojas)) if hojas else 0,
        }
        context = {
            'tablero': tablero,
            'tareas': ordenadas,
            'resumen': resumen,
            'usuarios': _usuarios_empresa(empresa),
            'estados': Tarea.ESTADO,
            'prioridades': Tarea.PRIORIDAD,
            'roles': TareaAsignacion.ROL,
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
            services.crear_tarea(
                tablero=tablero, usuario=request.user, titulo=titulo, padre=padre,
                prioridad=request.POST.get('prioridad') or 'MEDIA',
                fecha_inicio_plan=ini, fecha_fin_plan=fin,
                duracion_dias=dias, duracion_horas=horas,
                es_hito=bool(request.POST.get('es_hito')),
                perfil_sugerido=(request.POST.get('perfil_sugerido') or '').strip())
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
            services.recalcular_tablero(tablero)
            services.evaluar_cierre(tarea)
            services.registrar_actividad(tarea, request.user, 'EDITADA', detalle="Editó la tarea")
            messages.success(request, "Tarea actualizada.")

        elif accion == 'eliminar_tarea' and tarea:
            folio = tarea.folio
            tarea.delete()  # CASCADE en Python borra hijos/asignaciones/etc.
            services.recalcular_tablero(tablero)
            messages.info(request, f"Tarea {folio} eliminada.")
            return redirect(base_url)

        elif accion == 'cambiar_estado' and tarea:
            nuevo = request.POST.get('estado')
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
                services.recalcular_tablero(tablero)
                services.registrar_actividad(tarea, request.user, 'APROBO',
                                             detalle="Aprobó y completó la tarea")
                messages.success(request, f"{tarea.folio} aprobada y completada.")

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

        elif accion == 'confirmar' and tarea:
            asig = TareaAsignacion.objects.filter(
                tarea=tarea, usuario=request.user).first()
            if not asig:
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


def _orden_jerarquico(tareas):
    """Ordena las tareas para la Lista: cada raíz seguida de su subárbol (por
    orden/WBS). Las bloqueantes (fuera del WBS) van al final."""
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
    # Bloqueantes al final
    salida += [t for t in tareas if t.es_bloqueante]
    return salida
