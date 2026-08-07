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


def _es_admin_tareas(user):
    """El dueño (OWNER) o un superusuario ven todos los tableros de la empresa."""
    if user.is_superuser:
        return True
    perfil = getattr(user, 'perfil', None)
    return bool(perfil and getattr(perfil, 'tipo_usuario', None) == 'OWNER')


def _puede_ver_tablero(user, tablero):
    """Un usuario ve un tablero si es admin, su responsable, lo creó, es miembro
    invitado explícito, o tiene al menos una tarea asignada en él."""
    if _es_admin_tareas(user):
        return True
    if tablero.responsable_id == user.id or tablero.creado_por_id == user.id:
        return True
    if tablero.miembros.filter(id=user.id).exists():
        return True
    return TareaAsignacion.objects.filter(tarea__tablero=tablero, usuario=user).exists()


def _puede_gestionar_tablero(user, tablero):
    """Quién puede editar los ajustes del tablero (nombre, responsable, miembros,
    visibilidad, modo de cierre): admin, su responsable o quien lo creó."""
    if _es_admin_tareas(user):
        return True
    return tablero.responsable_id == user.id or tablero.creado_por_id == user.id


def _ve_todo_el_tablero(user, tablero):
    """True si el usuario ve TODAS las tareas del tablero (no solo las suyas):
    admin, responsable, creador, o tableros con visibilidad 'TODO'."""
    if tablero.visibilidad != 'ASIGNADAS':
        return True
    if _es_admin_tareas(user):
        return True
    return tablero.responsable_id == user.id or tablero.creado_por_id == user.id


_AVATAR_COLORS = ['bg-indigo-500', 'bg-emerald-500', 'bg-rose-500', 'bg-amber-500',
                  'bg-blue-500', 'bg-violet-500', 'bg-cyan-600', 'bg-pink-600']


def _personas_tablero(tablero, dets=None):
    """Quiénes pueden VER el tablero y con qué papel. Devuelve dicts:
    {'user', 'rol', 'interactua', 'color'}. 'interactua'=False → solo visor.
    Prioridad de rol: Responsable > Colaborador (asignado) > Creador > Solo visor."""
    dets = dets if dets is not None else list(tablero.tareas.all())
    orden = {'Responsable': 0, 'Colaborador': 1, 'Creador': 2, 'Solo visor': 3}
    personas = {}

    def add(u, rol, interactua):
        if not u:
            return
        prev = personas.get(u.id)
        if not prev or orden[rol] < orden[prev['rol']]:
            personas[u.id] = {'user': u, 'rol': rol, 'interactua': interactua}

    add(tablero.responsable, 'Responsable', True)
    for x in dets:
        for a in x.asignaciones.all():
            add(a.usuario, 'Colaborador', True)
    add(tablero.creado_por, 'Creador', True)
    for u in tablero.miembros.all():
        add(u, 'Solo visor', False)

    lista = sorted(personas.values(),
                   key=lambda p: (not p['interactua'],
                                  (p['user'].get_full_name() or p['user'].username).lower()))
    for i, p in enumerate(lista):
        p['color'] = _AVATAR_COLORS[i % len(_AVATAR_COLORS)]
    return lista


def _stats_tablero(tablero, dets):
    """Métricas para la tarjeta/encabezado: avance, atrasadas, bloqueadas,
    ventana de fechas, reprogramación vs la línea base y salud."""
    import datetime as _dt
    hojas = [x for x in dets if not x.es_resumen and not x.es_bloqueante]
    hoy = timezone.localdate()
    fin_semana = hoy + _dt.timedelta(days=(6 - hoy.weekday()))   # domingo de esta semana
    n = len(hojas)
    comp = sum(1 for x in hojas if x.estado == 'COMP')
    avance = round(sum(float(x.avance) for x in hojas) / n) if n else 0
    atrasadas = sum(1 for x in hojas
                    if x.fecha_fin_plan and x.fecha_fin_plan < hoy
                    and x.estado not in ('COMP', 'CANC'))
    vencen = sum(1 for x in hojas
                 if x.fecha_fin_plan and hoy <= x.fecha_fin_plan <= fin_semana
                 and x.estado not in ('COMP', 'CANC'))
    bloq = sum(1 for x in dets if x.estado == 'BLOQ')
    # Equipo: personas asignadas a cualquier tarea del tablero (distintas).
    equipo = {}
    for x in dets:
        for a in x.asignaciones.all():
            equipo.setdefault(a.usuario_id, a.usuario)
    fins = [x.fecha_fin_plan for x in hojas if x.fecha_fin_plan]
    inis = [x.fecha_inicio_plan for x in hojas if x.fecha_inicio_plan]
    fin_actual = max(fins) if fins else None
    ini_actual = min(inis) if inis else None
    reprog = None
    if tablero.fecha_fin_base and fin_actual:
        if fin_actual > tablero.fecha_fin_base:
            reprog = services.dias_habiles_entre(tablero.fecha_fin_base, fin_actual) - 1
        elif fin_actual < tablero.fecha_fin_base:
            reprog = -(services.dias_habiles_entre(fin_actual, tablero.fecha_fin_base) - 1)
    if n and comp == n:
        salud = 'completo'
    elif atrasadas:
        salud = 'atrasado'
    else:
        salud = 'en_tiempo'
    return {'n': n, 'comp': comp, 'avance': avance, 'atrasadas': atrasadas,
            'vencen': vencen, 'bloq': bloq, 'ini': ini_actual, 'fin': fin_actual,
            'reprog': reprog or None, 'salud': salud, 'equipo': list(equipo.values())}


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
        from django.db.models import Q
        ver_archivados = request.GET.get('archivados') == '1'
        base = Tablero.objects.operativos().filter(empresa=empresa)
        admin = _es_admin_tareas(request.user)
        if not admin:
            # Solo los tableros donde está involucrado (invitado explícito o por tarea).
            base = base.filter(Q(responsable=request.user) | Q(creado_por=request.user)
                               | Q(miembros=request.user)
                               | Q(tareas__asignaciones__usuario=request.user)).distinct()
        n_archivados = base.filter(activo=False).count()
        qs = base.filter(activo=not ver_archivados)
        tableros = list(qs.select_related('responsable', 'creado_por')
                        .prefetch_related('tareas__asignaciones__usuario', 'miembros'))
        for t in tableros:
            dets = list(t.tareas.all())
            t.stats = _stats_tablero(t, dets)
            t.personas = _personas_tablero(t, dets)
            t.puede_gestionar = _puede_gestionar_tablero(request.user, t)
        plantillas = list(Tablero.objects.filter(empresa=empresa, es_plantilla=True, activo=True)
                          .order_by('nombre')) if admin else []
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
            'visibilidades': Tablero.VISIBILIDAD,
            'ver_archivados': ver_archivados,
            'n_archivados': n_archivados,
            'seccion': 'tareas',
        }
        return render(request, self.template_name, context)

    def post(self, request):
        empresa = _empresa(request)
        if not empresa:
            return redirect('home')
        accion = request.POST.get('accion') or 'crear_tablero'

        es_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        if accion in ('archivar_tablero', 'reactivar_tablero'):
            from django.urls import reverse
            tb = Tablero.objects.filter(id=request.POST.get('tablero_id'), empresa=empresa).first()
            if not tb or not _puede_gestionar_tablero(request.user, tb):
                messages.error(request, "No puedes archivar ese tablero.")
                return redirect('admon_tareas:tableros')
            tb.activo = (accion == 'reactivar_tablero')
            tb.save(update_fields=['activo'])
            messages.success(request, f"Tablero «{tb.nombre}» "
                             f"{'reactivado' if tb.activo else 'archivado'}.")
            # Quédate en la lista desde la que actuaste: archivar viene de activos,
            # reactivar viene de archivados.
            destino = reverse('admon_tareas:tableros')
            return redirect(f"{destino}?archivados=1" if accion == 'reactivar_tablero' else destino)

        if accion == 'crear_tipo':
            nombre = (request.POST.get('nombre') or '').strip()
            if not nombre:
                if es_ajax:
                    return JsonResponse({'ok': False, 'error': 'nombre vacío'}, status=400)
                return redirect('admon_tareas:tableros')
            orden = TipoTablero.objects.filter(empresa=empresa).count()
            tp, creada = TipoTablero.objects.get_or_create(
                empresa=empresa, nombre=nombre[:60], defaults={'orden': orden})
            if not tp.activo:
                tp.activo = True
                tp.save(update_fields=['activo'])
            if es_ajax:
                return JsonResponse({'ok': True, 'id': tp.id, 'nombre': tp.nombre})
            messages.success(request, f"Tipo '{tp.nombre}' agregado.")
            return redirect('admon_tareas:tableros')

        if accion == 'toggle_tipo':
            tp = TipoTablero.objects.filter(id=request.POST.get('tipo_id'), empresa=empresa).first()
            if tp:
                tp.activo = not tp.activo
                tp.save(update_fields=['activo'])
                if es_ajax:
                    return JsonResponse({'ok': True, 'id': tp.id, 'activo': tp.activo,
                                         'nombre': tp.nombre})
                messages.info(request, f"Tipo '{tp.nombre}' {'activado' if tp.activo else 'desactivado'}.")
            elif es_ajax:
                return JsonResponse({'ok': False}, status=404)
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
        visibilidad = request.POST.get('visibilidad')
        if visibilidad not in dict(Tablero.VISIBILIDAD):
            visibilidad = 'TODO'
        tablero = Tablero.objects.create(
            empresa=empresa, codigo=(request.POST.get('codigo') or f'TAB-{n:04d}').strip()[:20],
            nombre=nombre, descripcion=(request.POST.get('descripcion') or '').strip(),
            tipo=tipo,
            modo_cierre=request.POST.get('modo_cierre') or 'TODOS',
            visibilidad=visibilidad,
            responsable_id=request.POST.get('responsable') or None,
            fecha_inicio=request.POST.get('fecha_inicio') or None,
            fecha_fin=request.POST.get('fecha_fin') or None,
            es_plantilla=bool(request.POST.get('es_plantilla')),
            creado_por=request.user)
        # Miembros invitados explícitos (pueden ver el tablero aunque no tengan tarea).
        ids = [int(i) for i in request.POST.getlist('miembros') if i.isdigit()]
        if ids:
            tablero.miembros.set(_usuarios_empresa(empresa).filter(id__in=ids))
        messages.success(request, f"Tablero {tablero.codigo} creado.")
        return redirect('admon_tareas:tablero_detalle', pk=tablero.pk)


class MisTareasView(LoginRequiredMixin, View):
    """Panel personal: las tareas asignadas al usuario, agrupadas por urgencia."""
    template_name = 'admon_tareas/mis_tareas.html'

    def get(self, request):
        import datetime as _dt
        empresa = _empresa(request)
        if not empresa:
            return redirect('home')
        hoy = timezone.localdate()
        fin_semana = hoy + _dt.timedelta(days=(6 - hoy.weekday()))

        asigs = list(TareaAsignacion.objects.filter(
            usuario=request.user, tarea__empresa=empresa, tarea__tablero__activo=True)
            .exclude(tarea__estado__in=['COMP', 'CANC'])
            .select_related('tarea', 'tarea__tablero'))

        def _fin(a):
            return a.tarea.fecha_fin_plan or _dt.date.max
        asigs.sort(key=_fin)

        bloqueos = [a for a in asigs if a.tarea.es_bloqueante]           # debo resolver
        resto = [a for a in asigs if not a.tarea.es_bloqueante]
        bloqueadas = [a for a in resto if a.tarea.estado == 'BLOQ']      # esperando desbloqueo
        activas = [a for a in resto if a.tarea.estado != 'BLOQ']
        atrasadas = [a for a in activas if a.tarea.fecha_fin_plan and a.tarea.fecha_fin_plan < hoy]
        semana = [a for a in activas
                  if a.tarea.fecha_fin_plan and hoy <= a.tarea.fecha_fin_plan <= fin_semana]
        proximas = [a for a in activas
                    if not a.tarea.fecha_fin_plan or a.tarea.fecha_fin_plan > fin_semana]

        context = {
            'total': len(asigs),
            'bloqueos': bloqueos,
            'atrasadas': atrasadas,
            'semana': semana,
            'proximas': proximas,
            'bloqueadas': bloqueadas,
            'hoy': hoy,
            'seccion': 'tareas',
        }
        return render(request, self.template_name, context)


def _es_movil(request):
    """Celular o PWA instalada (excluye iPad → usa escritorio). Una vez detectado
    ?pwa=1 se recuerda en sesión para que la app instalada siga en modo móvil."""
    ua = request.META.get('HTTP_USER_AGENT', '').lower()
    es_tel = ('ipad' not in ua) and any(k in ua for k in ('android', 'iphone', 'mobile'))
    if request.GET.get('pwa') == '1':
        request.session['pwa_mode'] = True
    return es_tel or bool(request.session.get('pwa_mode'))


class MovilView(LoginRequiredMixin, View):
    """Pantalla móvil (PWA) del módulo de tareas: Mis tareas + mis tableros."""
    template_name = 'admon_tareas/movil/home.html'

    def get(self, request):
        import datetime as _dt
        from django.db.models import Q
        empresa = _empresa(request)
        if not empresa:
            return redirect('home')
        # En escritorio/iPad manda a la vista normal (a menos que sea PWA).
        if not _es_movil(request):
            return redirect('admon_tareas:tableros')

        hoy = timezone.localdate()
        fin_semana = hoy + _dt.timedelta(days=(6 - hoy.weekday()))
        asigs = list(TareaAsignacion.objects.filter(
            usuario=request.user, tarea__empresa=empresa, tarea__tablero__activo=True)
            .exclude(tarea__estado__in=['COMP', 'CANC'])
            .select_related('tarea', 'tarea__tablero'))
        asigs.sort(key=lambda a: a.tarea.fecha_fin_plan or _dt.date.max)
        bloqueos = [a for a in asigs if a.tarea.es_bloqueante]
        resto = [a for a in asigs if not a.tarea.es_bloqueante]
        atrasadas = [a for a in resto if a.tarea.estado != 'BLOQ'
                     and a.tarea.fecha_fin_plan and a.tarea.fecha_fin_plan < hoy]
        semana = [a for a in resto if a.tarea.estado != 'BLOQ'
                  and a.tarea.fecha_fin_plan and hoy <= a.tarea.fecha_fin_plan <= fin_semana]
        urgentes = bloqueos + atrasadas + semana
        proximas = [a for a in resto if a.tarea.estado != 'BLOQ'
                    and (not a.tarea.fecha_fin_plan or a.tarea.fecha_fin_plan > fin_semana)]

        qs = Tablero.objects.operativos().filter(empresa=empresa, activo=True)
        if not _es_admin_tareas(request.user):
            qs = qs.filter(Q(responsable=request.user) | Q(creado_por=request.user)
                           | Q(miembros=request.user)
                           | Q(tareas__asignaciones__usuario=request.user)).distinct()
        tableros = list(qs.select_related('responsable')
                        .prefetch_related('tareas__asignaciones__usuario'))
        for t in tableros:
            t.stats = _stats_tablero(t, list(t.tareas.all()))

        return render(request, self.template_name, {
            'empresa': empresa, 'hoy': hoy, 'total': len(asigs),
            'bloqueos': bloqueos, 'atrasadas': atrasadas, 'semana': semana,
            'urgentes': urgentes, 'proximas': proximas, 'tableros': tableros,
            'seccion': 'tareas',
        })


class MovilTareaView(LoginRequiredMixin, View):
    """Detalle de una tarea en versión móvil: datos, asignados, subtareas y las
    acciones clave (confirmar mi parte, cambiar estado) que reusan el POST normal."""
    template_name = 'admon_tareas/movil/tarea.html'

    def get(self, request, pk):
        empresa = _empresa(request)
        if not empresa:
            return redirect('home')
        tarea = get_object_or_404(Tarea.objects.select_related('tablero', 'padre'),
                                  pk=pk, empresa=empresa)
        if not _puede_ver_tablero(request.user, tarea.tablero):
            return redirect('admon_tareas:movil')
        subtareas = list(tarea.hijos.exclude(es_bloqueante=True)
                         .prefetch_related('asignaciones__usuario').order_by('orden', 'ruta_wbs'))
        return render(request, self.template_name, {
            'empresa': empresa, 'tablero': tarea.tablero, 't': tarea,
            'asignaciones': tarea.asignaciones.select_related('usuario').all(),
            'subtareas': subtareas,
            'mi_asignacion': tarea.asignaciones.filter(usuario=request.user).first(),
            'estados': Tarea.ESTADO,
            'seccion': 'tareas',
        })


class TableroDetalleView(LoginRequiredMixin, View):
    template_name = 'admon_tareas/tablero_detalle.html'

    def get(self, request, pk):
        empresa = _empresa(request)
        if not empresa:
            return redirect('home')
        tablero = get_object_or_404(Tablero, pk=pk, empresa=empresa)
        if not _puede_ver_tablero(request.user, tablero):
            messages.error(request, "No tienes acceso a ese tablero.")
            return redirect('admon_tareas:tableros')
        # Recalcula derivados (WBS, avance, fechas de fases + cascada) al abrir,
        # para que la vista siempre sea consistente y se auto-corrija.
        services.recalcular_tablero(tablero)
        tareas = list(tablero.tareas.select_related('padre')
                      .prefetch_related('asignaciones__usuario')
                      .order_by('orden', 'ruta_wbs', 'id'))
        deps = list(TareaDependencia.objects.filter(sucesora__tablero=tablero)
                    .select_related('predecesora'))
        personas = _personas_tablero(tablero, tareas)   # roster completo (antes de filtrar)
        # Visibilidad "solo mis tareas": un miembro limitado ve únicamente las tareas
        # que tiene asignadas (más sus fases/ancestros como contexto de la jerarquía).
        solo_mias = not _ve_todo_el_tablero(request.user, tablero)
        if solo_mias:
            mis_ids = set(TareaAsignacion.objects.filter(
                tarea__tablero=tablero, usuario=request.user).values_list('tarea_id', flat=True))
            by_id = {t.id: t for t in tareas}
            visibles = set(mis_ids)
            for tid in list(mis_ids):
                t = by_id.get(tid)
                while t and t.padre_id:
                    visibles.add(t.padre_id)
                    t = by_id.get(t.padre_id)
            tareas = [t for t in tareas if t.id in visibles]
            deps = [d for d in deps if d.predecesora_id in visibles and d.sucesora_id in visibles]
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
        # Grupo (etapa raíz) de cada fila, para agrupar/colapsar en la Lista, y
        # conteo de tareas hoja por etapa.
        _by_id = {t.id: t for t in ordenadas}

        def _raiz(t):
            while t.padre_id and _by_id.get(t.padre_id):
                t = _by_id[t.padre_id]
            return t
        for t in ordenadas:
            t.n_hijas = 0
        for t in ordenadas:
            r = _raiz(t)
            t.grupo = r.id if r.es_etapa else ''
            if r.es_etapa and not t.es_etapa and not t.es_resumen and not t.es_bloqueante:
                r.n_hijas += 1
        resumen = _stats_tablero(tablero, tareas)
        # En celular/PWA: vista móvil del tablero (lista por etapas), sin Gantt/Kanban.
        if _es_movil(request):
            return render(request, 'admon_tareas/movil/tablero.html', {
                'empresa': empresa, 'tablero': tablero, 'tareas': ordenadas,
                'resumen': resumen, 'solo_mias': solo_mias,
                'hoy': timezone.localdate(), 'seccion': 'tareas',
            })
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
            'solo_mias': solo_mias,
            'modos': Tablero.MODO_CIERRE,
            'visibilidades': Tablero.VISIBILIDAD,
            'puede_gestionar': _puede_gestionar_tablero(request.user, tablero),
            'miembros_ids': list(tablero.miembros.values_list('id', flat=True)),
            'personas': personas,
            'seccion': 'tareas',
        }
        return render(request, self.template_name, context)

    def post(self, request, pk):
        empresa = _empresa(request)
        if not empresa:
            return redirect('home')
        from django.urls import reverse
        tablero = get_object_or_404(Tablero, pk=pk, empresa=empresa)
        if not _puede_ver_tablero(request.user, tablero):
            messages.error(request, "No tienes acceso a ese tablero.")
            return redirect('admon_tareas:tableros')
        accion = request.POST.get('accion')
        base_url = reverse('admon_tareas:tablero_detalle', kwargs={'pk': pk})

        def volver_a_tarea():
            tid = request.POST.get('tarea_id')
            # Si la acción vino de la vista móvil, regresa a la tarea móvil.
            if request.POST.get('next') == 'movil' and tid:
                from django.urls import reverse
                return redirect(reverse('admon_tareas:movil_tarea', kwargs={'pk': tid}))
            return redirect(f"{base_url}?t={tid}" if tid else base_url)
        volver = volver_a_tarea()

        if accion == 'editar_tablero':
            if not _puede_gestionar_tablero(request.user, tablero):
                messages.error(request, "No puedes editar los ajustes de este tablero.")
                return redirect(base_url)
            nombre = (request.POST.get('nombre') or '').strip()
            if nombre:
                tablero.nombre = nombre[:180]
            tablero.descripcion = (request.POST.get('descripcion') or '').strip()
            modo = request.POST.get('modo_cierre')
            if modo in dict(Tablero.MODO_CIERRE):
                tablero.modo_cierre = modo
            vis = request.POST.get('visibilidad')
            if vis in dict(Tablero.VISIBILIDAD):
                tablero.visibilidad = vis
            tablero.responsable_id = request.POST.get('responsable') or None
            tablero.save(update_fields=['nombre', 'descripcion', 'modo_cierre',
                                        'visibilidad', 'responsable'])
            ids = [int(i) for i in request.POST.getlist('miembros') if i.isdigit()]
            tablero.miembros.set(_usuarios_empresa(empresa).filter(id__in=ids))
            messages.success(request, "Ajustes del tablero actualizados.")
            return redirect(base_url)

        if accion == 'archivar_tablero':
            if not _puede_gestionar_tablero(request.user, tablero):
                messages.error(request, "No puedes archivar este tablero.")
                return redirect(base_url)
            tablero.activo = False
            tablero.save(update_fields=['activo'])
            messages.success(request, f"Tablero «{tablero.nombre}» archivado. "
                             "Puedes reactivarlo desde «Archivados».")
            return redirect('admon_tareas:tableros')

        if accion == 'fijar_linea_base':
            from django.db.models import Max as _Max
            fin = (tablero.tareas.filter(es_bloqueante=False, fecha_fin_plan__isnull=False)
                   .aggregate(m=_Max('fecha_fin_plan'))['m'])
            tablero.fecha_fin_base = fin
            tablero.save(update_fields=['fecha_fin_base'])
            messages.success(request, "Línea base fijada al plan actual.")
            return redirect(base_url)

        if accion == 'crear_etapa':
            titulo = (request.POST.get('titulo') or '').strip()
            if not titulo:
                messages.error(request, "La etapa necesita un título.")
                return volver
            # Una etapa es un grupo de primer nivel (sin padre) y sin duración propia.
            services.crear_tarea(tablero=tablero, usuario=request.user, titulo=titulo,
                                 padre=None, es_etapa=True)
            messages.success(request, f"Etapa «{titulo}» agregada.")
            return redirect(base_url)

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

        if accion == 'mover_a_etapa' and tarea:
            if tarea.es_etapa or tarea.es_bloqueante:
                messages.error(request, "Esa fila no se puede mover a una etapa.")
                return volver
            etapa_id = request.POST.get('etapa_id') or ''
            padre_id = request.POST.get('padre_id') or ''   # soltada como subtarea de otra tarea
            nueva_padre = None
            if padre_id:
                cand = tablero.tareas.filter(id=padre_id).exclude(es_bloqueante=True).first()
                if not cand or cand.id == tarea.id:
                    messages.error(request, "No se puede anidar ahí.")
                    return volver
                # Evita ciclos: el nuevo padre no puede ser descendiente de la tarea.
                _by = {x.id: x for x in tablero.tareas.all()}
                cur = cand
                while cur is not None:
                    if cur.id == tarea.id:
                        messages.error(request, "Eso crearía un ciclo.")
                        return volver
                    cur = _by.get(cur.padre_id)
                nueva_padre = cand
            elif etapa_id:
                nueva_padre = tablero.tareas.filter(id=etapa_id, es_etapa=True).first()
                if not nueva_padre:
                    messages.error(request, "Etapa no válida.")
                    return volver
            # Hermanos del nuevo padre (sin la arrastrada ni bloqueantes), en orden.
            hermanos = list(tablero.tareas.filter(padre=nueva_padre, es_bloqueante=False)
                            .exclude(id=tarea.id).order_by('orden', 'ruta_wbs', 'id'))
            # Posición exacta: antes/después de la tarea de referencia (ref_id).
            ref_id = request.POST.get('ref_id')
            posicion = request.POST.get('posicion')  # 'antes' | 'despues'
            idx = len(hermanos)   # por defecto, al final
            if ref_id and ref_id != str(tarea.id):
                for i, h in enumerate(hermanos):
                    if str(h.id) == str(ref_id):
                        idx = i + 1 if posicion == 'despues' else i
                        break
            hermanos.insert(idx, tarea)
            tarea.padre = nueva_padre
            for i, h in enumerate(hermanos, start=1):
                h.orden = i
            tarea.save(update_fields=['padre', 'orden'])
            otros = [h for h in hermanos if h.id != tarea.id]
            if otros:
                Tarea.objects.bulk_update(otros, ['orden'])
            services.recalcular_tablero(tablero)
            messages.success(request, f"Tarea movida a «{nueva_padre.titulo}»." if nueva_padre
                             else "Tarea movida fuera de etapas.")
            return volver

        if accion == 'editar_tarea' and tarea:
            tarea.titulo = (request.POST.get('titulo') or tarea.titulo).strip()
            tarea.descripcion = request.POST.get('descripcion', tarea.descripcion)
            tarea.prioridad = request.POST.get('prioridad') or tarea.prioridad
            tarea.es_hito = bool(request.POST.get('es_hito'))
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
        if not _puede_ver_tablero(request.user, tarea.tablero):
            return HttpResponse(status=403)
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
            # Etapas del tablero para el selector "Mover a etapa".
            'etapas': list(tarea.tablero.tareas.filter(es_etapa=True).order_by('orden', 'ruta_wbs')),
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

    # Intervalos de bloqueo por tarea (para partir su barra: split task).
    bloqueos_por_tarea = {}
    for dep in deps:
        if dep.origen != 'BLOQUEO':
            continue
        b = dep.predecesora
        bsi = idx_de(b.fecha_inicio_plan)
        fin_b = b.fecha_fin_real or b.fecha_fin_plan
        bei = idx_de(fin_b) if fin_b else bsi
        if bsi is None:
            continue
        if bei is None:
            bei = bsi
        bloqueos_por_tarea.setdefault(dep.sucesora_id, []).append((bsi, bei))

    fila = {}
    for row, t in enumerate(ordenadas):
        t.grow = row
        t.gy = row * ROWH + BAR_TOP
        t.gsplit = False
        t.gsegs = None
        t.gconn = None
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
            # Split: parte la barra alrededor del/los periodo(s) de bloqueo.
            if (not t.es_resumen and not t.es_hito and not t.es_bloqueante
                    and not t.gbloq_punto and bloqueos_por_tarea.get(t.id)):
                segs, cur = [], si
                for bsi, bei in sorted(bloqueos_por_tarea[t.id]):
                    bsi, bei = max(bsi, si), min(bei, ei)
                    if bei < si or bsi > ei:
                        continue
                    if bsi > cur:
                        segs.append((cur, bsi - 1))
                    cur = max(cur, bei + 1)
                if cur <= ei:
                    segs.append((cur, ei))
                segs = [(a, b) for (a, b) in segs if b >= a]
                if len(segs) > 1:
                    t.gsplit = True
                    t.gsegs = [{'x': a * CW, 'w': (b - a + 1) * CW} for (a, b) in segs]
                    fseg, lseg = t.gsegs[0], t.gsegs[-1]
                    x0 = fseg['x'] + fseg['w']
                    t.gconn = {'x': x0, 'w': lseg['x'] - x0, 'y': t.gy + BAR_H // 2}
        else:
            t.gvis = False

    # Segmentos de dependencia (flechas).
    por_id = {t.id: t for t in ordenadas}
    segmentos = []
    for dep in deps:
        p = fila.get(dep.predecesora_id)
        s = fila.get(dep.sucesora_id)
        if not p or not s:
            continue
        y_pred = p[2] * ROWH + ROWH / 2
        y_suc = s[2] * ROWH + ROWH / 2
        suc = por_id.get(dep.sucesora_id)
        if dep.origen == 'BLOQUEO' and suc and suc.gsplit:
            # Tarea partida: fin del 1er segmento → inicio del bloqueo, y fin del
            # bloqueo → inicio del 2do segmento.
            seg1, seg2 = suc.gsegs[0], suc.gsegs[-1]
            bsi, bei = p[0], p[1]
            segmentos.append({'x1': seg1['x'] + seg1['w'], 'y1': y_suc,
                              'x2': bsi * CW, 'y2': y_pred})
            segmentos.append({'x1': (bei + 1) * CW, 'y1': y_pred,
                              'x2': seg2['x'], 'y2': y_suc})
        else:
            segmentos.append({'x1': (p[1] + 1) * CW, 'y1': y_pred,
                              'x2': s[0] * CW, 'y2': y_suc})

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
