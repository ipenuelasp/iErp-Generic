"""
Lógica derivada del módulo de tareas. TODO aquí, nunca en señales:
- folio consecutivo por empresa
- recálculo de WBS / nivel / es_resumen
- rollup de avance del padre desde los hijos (ponderado por peso)
- derivación del estado de la tarea desde las confirmaciones + modo_cierre
- bitácora de actividad
Se llama explícito desde las vistas.
"""
import decimal

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .models import Tablero, Tarea, TareaAsignacion, TareaActividad, TareaDependencia


import datetime


# --------------------------------------------------------------------------
# Fechas: duración (días hábiles + horas) → fecha fin
# --------------------------------------------------------------------------
def sumar_dias_habiles(fecha, n):
    """Avanza n días hábiles (lun–vie) a partir de `fecha`. n=0 devuelve la misma."""
    if not fecha:
        return None
    d = fecha
    pasos = 0
    while pasos < n:
        d = d + datetime.timedelta(days=1)
        if d.weekday() < 5:   # 0-4 = lun-vie
            pasos += 1
    return d


def restar_dias_habiles(fecha, n):
    """Retrocede n días hábiles (lun–vie) desde `fecha`."""
    if not fecha:
        return None
    d = fecha
    pasos = 0
    while pasos < n:
        d = d - datetime.timedelta(days=1)
        if d.weekday() < 5:
            pasos += 1
    return d


def desplazar_habiles(fecha, n):
    """Desplaza n días hábiles con signo (n>0 hacia adelante, n<0 hacia atrás)."""
    if not fecha:
        return None
    return sumar_dias_habiles(fecha, n) if n >= 0 else restar_dias_habiles(fecha, -n)


def dias_habiles_entre(a, b):
    """Cuenta los días hábiles (lun–vie) entre a y b, inclusivo. Mínimo 1."""
    if not a or not b:
        return None
    if b < a:
        a, b = b, a
    n, d = 0, a
    while d <= b:
        if d.weekday() < 5:
            n += 1
        d = d + datetime.timedelta(days=1)
    return n or 1


def calcular_fin_plan(inicio, dias, horas):
    """fecha fin = inicio + (días hábiles), contando el día de inicio como el 1.
    Si solo hay horas (día 0) la tarea termina el mismo día. Sin inicio o sin
    duración, devuelve None (se respeta la fecha fin capturada a mano)."""
    if not inicio:
        return None
    dias = int(dias or 0)
    horas = int(horas or 0)
    if dias <= 0 and horas > 0:
        dias = 1
    if dias <= 0:
        return None
    # el día de inicio cuenta como el primer día hábil
    inicio_habil = inicio
    while inicio_habil.weekday() >= 5:   # si cae en finde, arranca el lunes
        inicio_habil = inicio_habil + datetime.timedelta(days=1)
    return sumar_dias_habiles(inicio_habil, dias - 1)


# --------------------------------------------------------------------------
# Dependencias (secuencia entre tareas)
# --------------------------------------------------------------------------
def _bloquea(dep):
    """¿Esta dependencia impide que la sucesora avance ahora?
    FS: la predecesora debe estar COMPLETADA. SS: debe haber ARRANCADO (no PEND).
    FF/SF: sólo informativas (no bloquean el arranque)."""
    p = dep.predecesora
    if dep.tipo == 'FS':
        return p.estado != 'COMP'
    if dep.tipo == 'SS':
        return p.estado == 'PEND'
    return False


def bloqueada_por(tarea):
    """Lista de dependencias (predecesoras) que impiden avanzar la tarea."""
    deps = TareaDependencia.objects.filter(sucesora=tarea).select_related('predecesora')
    return [d for d in deps if _bloquea(d)]


def _inicio_requerido(suc):
    """Fecha de inicio más temprana permitida para `suc` según TODAS sus
    predecesoras (toma la más restrictiva). None si no tiene predecesoras con
    fechas o si la propia tarea no tiene fechas."""
    if not suc.fecha_inicio_plan or not suc.fecha_fin_plan:
        return None
    dur = dias_habiles_entre(suc.fecha_inicio_plan, suc.fecha_fin_plan) or 1
    reqs = []
    # Solo las dependencias del cronograma (PLANEADA) reprograman fechas; las de
    # BLOQUEO son impedimentos de estatus, no mueven el calendario.
    for dep in (TareaDependencia.objects.filter(sucesora=suc, origen='PLANEADA')
                .select_related('predecesora')):
        p = dep.predecesora
        if not p.fecha_inicio_plan or not p.fecha_fin_plan:
            continue
        lag = dep.desfase_dias or 0
        if dep.tipo == 'FS':          # empieza después de que la otra termina
            reqs.append(desplazar_habiles(p.fecha_fin_plan, 1 + lag))
        elif dep.tipo == 'SS':        # empieza cuando la otra empieza
            reqs.append(desplazar_habiles(p.fecha_inicio_plan, lag))
        elif dep.tipo == 'FF':        # termina cuando la otra termina
            fin = desplazar_habiles(p.fecha_fin_plan, lag)
            reqs.append(restar_dias_habiles(fin, dur - 1))
        else:                          # SF
            fin = desplazar_habiles(p.fecha_inicio_plan, lag)
            reqs.append(restar_dias_habiles(fin, dur - 1))
    return max(reqs) if reqs else None


def reprogramar_cascada(tarea_movida, usuario):
    """Reprograma las sucesoras (directas e indirectas) para que queden pegadas a
    su predecesora según la dependencia y su desfase. Las mueve en AMBOS sentidos:
    si la predecesora se recorre a más tarde, las empuja; si se acorta/adelanta,
    las jala hacia atrás. Devuelve la lista de tareas recorridas.

    Nota: los enlazadas quedan una tras otra. Para dejar un hueco intencional
    entre dos tareas, usar el desfase (lag) de la dependencia."""
    from collections import deque
    cambiadas = []
    cola = deque([tarea_movida])
    iters = 0
    while cola and iters < 1000:
        iters += 1
        actual = cola.popleft()
        for dep in (TareaDependencia.objects.filter(predecesora=actual, origen='PLANEADA')
                    .select_related('sucesora')):
            suc = dep.sucesora
            if not suc.fecha_inicio_plan or not suc.fecha_fin_plan:
                continue
            req = _inicio_requerido(suc)
            if req and req != suc.fecha_inicio_plan:
                dur = dias_habiles_entre(suc.fecha_inicio_plan, suc.fecha_fin_plan) or 1
                suc.fecha_inicio_plan = req
                suc.fecha_fin_plan = sumar_dias_habiles(req, dur - 1)
                suc.duracion_dias = dur
                suc.save(update_fields=['fecha_inicio_plan', 'fecha_fin_plan', 'duracion_dias'])
                registrar_actividad(
                    suc, usuario, 'FECHA',
                    detalle=f"Recorrida en cascada por depender de {actual.folio}")
                cambiadas.append(suc)
                cola.append(suc)   # sus propias sucesoras también podrían moverse
    return cambiadas


def crearia_ciclo(predecesora, sucesora):
    """True si agregar predecesora→sucesora cerraría un ciclo (ya hay camino
    sucesora→…→predecesora siguiendo las dependencias existentes)."""
    objetivo = predecesora.id
    visto = set()
    frontera = [sucesora.id]
    while frontera:
        actual = frontera.pop()
        if actual == objetivo:
            return True
        if actual in visto:
            continue
        visto.add(actual)
        frontera.extend(
            TareaDependencia.objects.filter(predecesora_id=actual)
            .values_list('sucesora_id', flat=True))
    return False


# --------------------------------------------------------------------------
# Folio
# --------------------------------------------------------------------------
def siguiente_folio(empresa):
    """TSK + consecutivo de 10 dígitos, por empresa."""
    ultimo = (Tarea.objects.filter(empresa=empresa)
              .exclude(folio='').order_by('-folio').values_list('folio', flat=True).first())
    n = 0
    if ultimo and ultimo.startswith('TSK'):
        try:
            n = int(ultimo[3:])
        except ValueError:
            n = 0
    return f"TSK{n + 1:010d}"


# --------------------------------------------------------------------------
# Actividad (bitácora)
# --------------------------------------------------------------------------
def registrar_actividad(tarea, usuario, accion, *, campo='', valor_ant='', valor_nue='', detalle=''):
    return TareaActividad.objects.create(
        tarea=tarea, usuario=usuario if getattr(usuario, 'pk', None) else None,
        accion=accion, campo=campo or '', valor_ant=str(valor_ant or ''),
        valor_nue=str(valor_nue or ''), detalle=detalle or '')


# --------------------------------------------------------------------------
# Recalcular estructura (WBS, nivel, es_resumen) + avance
# --------------------------------------------------------------------------
def recalcular_tablero(tablero):
    """Recalcula ruta_wbs, nivel y es_resumen de todas las tareas del tablero, y
    hace el rollup de avance. Las tareas bloqueantes (es_bloqueante) viven fuera
    del WBS: ruta_wbs='' y no entran en la numeración ni en el rollup del padre."""
    tareas = list(Tarea.objects.filter(tablero=tablero))
    por_padre = {}
    for t in tareas:
        por_padre.setdefault(t.padre_id, []).append(t)
    for hijos in por_padre.values():
        hijos.sort(key=lambda x: (x.orden, x.id))

    cambiadas = []

    def _num(lista, prefijo, nivel):
        i = 0
        for t in lista:
            if t.es_bloqueante:
                # Fuera del WBS
                if t.ruta_wbs != '' or t.nivel != nivel:
                    t.ruta_wbs = ''
                    t.nivel = nivel
                    cambiadas.append(t)
                continue
            i += 1
            wbs = f"{prefijo}{i}" if not prefijo else f"{prefijo}.{i}"
            hijos = [h for h in por_padre.get(t.id, []) if not h.es_bloqueante]
            es_res = bool(hijos)
            if t.ruta_wbs != wbs or t.nivel != nivel or t.es_resumen != es_res:
                t.ruta_wbs = wbs
                t.nivel = nivel
                t.es_resumen = es_res
                cambiadas.append(t)
            _num(por_padre.get(t.id, []), wbs, nivel + 1)

    _num(por_padre.get(None, []), '', 0)

    if cambiadas:
        # Puede haber duplicados en la lista; dedup por id conservando el objeto.
        vistos = {}
        for t in cambiadas:
            vistos[t.id] = t
        Tarea.objects.bulk_update(vistos.values(), ['ruta_wbs', 'nivel', 'es_resumen'])

    _rollup_avance(tablero)


def _rollup_avance(tablero):
    """Avance del padre = promedio ponderado por peso de sus hijos (no bloqueantes),
    recursivo. En hojas se respeta el avance capturado."""
    tareas = list(Tarea.objects.filter(tablero=tablero))
    por_id = {t.id: t for t in tareas}
    hijos_de = {}
    for t in tareas:
        if t.padre_id and not t.es_bloqueante:
            hijos_de.setdefault(t.padre_id, []).append(t)

    memo = {}

    def _av(t):
        if t.id in memo:
            return memo[t.id]
        hijos = hijos_de.get(t.id, [])
        if not hijos:
            val = decimal.Decimal(t.avance)
        else:
            peso_total = sum((decimal.Decimal(h.peso) for h in hijos), decimal.Decimal('0'))
            if peso_total <= 0:
                val = decimal.Decimal('0')
            else:
                val = sum((_av(h) * decimal.Decimal(h.peso) for h in hijos),
                          decimal.Decimal('0')) / peso_total
            val = val.quantize(decimal.Decimal('0.01'))
        memo[t.id] = val
        return val

    a_guardar = []
    for t in tareas:
        if t.es_resumen and not t.es_bloqueante:
            nuevo = _av(t)
            if decimal.Decimal(t.avance) != nuevo:
                t.avance = nuevo
                a_guardar.append(t)
    if a_guardar:
        Tarea.objects.bulk_update(a_guardar, ['avance'])


# --------------------------------------------------------------------------
# Derivación del estado desde las confirmaciones
# --------------------------------------------------------------------------
def evaluar_cierre(tarea):
    """Deriva el estado de una tarea HOJA según sus confirmaciones y el modo de
    cierre del tablero. No toca tareas resumen, bloqueadas, canceladas ni ya
    completadas (esas las cierra el responsable con cerrar_tarea)."""
    if tarea.es_resumen or tarea.estado in ('BLOQ', 'CANC', 'COMP'):
        return tarea.estado
    asigs = list(tarea.asignaciones.all())
    if not asigs:
        return tarea.estado

    modo = tarea.tablero.modo_cierre
    if modo == 'RESPONSABLE':
        resp = [a for a in asigs if a.rol == 'RESP'] or asigs
        listo = all(a.completado for a in resp)
    elif modo == 'CUALQUIERA':
        listo = any(a.completado for a in asigs)
    else:  # TODOS
        listo = all(a.completado for a in asigs)

    nuevo = 'REVI' if listo else ('PROC' if any(a.completado for a in asigs) else tarea.estado)
    if nuevo != tarea.estado:
        tarea.estado = nuevo
        tarea.save(update_fields=['estado'])
    return tarea.estado


def confirmar_asignacion(asignacion, usuario, *, completado=True, nota=''):
    """Marca (o desmarca) la confirmación individual de una persona y re-evalúa
    el cierre de la tarea."""
    asignacion.completado = completado
    asignacion.completado_en = timezone.now() if completado else None
    if nota:
        asignacion.nota_cierre = nota[:500]
    asignacion.save(update_fields=['completado', 'completado_en', 'nota_cierre'])
    registrar_actividad(
        asignacion.tarea, usuario, 'CONFIRMO' if completado else 'DESCONFIRMO',
        detalle=f"{usuario} {'confirmó' if completado else 'quitó su confirmación de'} su parte")
    evaluar_cierre(asignacion.tarea)


# --------------------------------------------------------------------------
# Bloqueos (generan una tarea bloqueante, fuera del WBS)
# --------------------------------------------------------------------------
def _delay_bloqueo(inicio, fin):
    """Días hábiles que un bloqueo (de `inicio` a `fin`) le agrega a la tarea."""
    if not inicio or not fin or fin <= inicio:
        return 0
    return (dias_habiles_entre(inicio, fin) or 1) - 1


def _aplicar_delay_bloqueo(dep, bloqueada, delay_nuevo, usuario):
    """Empuja (o regresa) el fin de la tarea bloqueada por la diferencia entre el
    retraso ya aplicado (guardado en dep.desfase_dias) y el nuevo. Luego recorre
    en cascada a sus dependientes de cronograma."""
    impuesto = dep.desfase_dias or 0
    diff = delay_nuevo - impuesto
    if dep.desfase_dias != delay_nuevo:
        dep.desfase_dias = delay_nuevo
        dep.save(update_fields=['desfase_dias'])
    if diff == 0 or not bloqueada.fecha_fin_plan:
        return
    bloqueada.fecha_fin_plan = desplazar_habiles(bloqueada.fecha_fin_plan, diff)
    if bloqueada.fecha_inicio_plan:
        bloqueada.duracion_dias = dias_habiles_entre(
            bloqueada.fecha_inicio_plan, bloqueada.fecha_fin_plan)
    bloqueada.save(update_fields=['fecha_fin_plan', 'duracion_dias'])
    registrar_actividad(
        bloqueada, usuario, 'FECHA',
        detalle=f"Fin recorrido {diff:+d} día(s) hábil(es) por el bloqueo")
    reprogramar_cascada(bloqueada, usuario)


@transaction.atomic
def bloquear(*, tarea, usuario, motivo, titulo, asignados_ids=None, fecha_compromiso=None):
    """Marca una tarea como bloqueada CREANDO la tarea que la desbloquea. En una
    sola transacción: crea la Tarea bloqueante (padre=None, es_bloqueante=True),
    la dependencia origen='BLOQUEO' y pone la tarea en BLOQ. Nunca se bloquea sin
    generar la bloqueante."""
    tablero = tarea.tablero
    empresa = tablero.empresa
    asignados_ids = [a for a in (asignados_ids or []) if a]
    agg = Tarea.objects.filter(tablero=tablero, padre__isnull=True).aggregate(m=Max('orden'))
    bloqueante = Tarea.objects.create(
        empresa=empresa, tablero=tablero, padre=None, es_bloqueante=True,
        titulo=titulo.strip(), folio=siguiente_folio(empresa), prioridad='ALTA',
        estado='PROC' if asignados_ids else 'PEND',
        fecha_inicio_plan=timezone.localdate(), fecha_fin_plan=fecha_compromiso or None,
        orden=(agg['m'] or 0) + 1, creado_por=usuario)
    for uid in asignados_ids:
        TareaAsignacion.objects.get_or_create(
            tarea=bloqueante, usuario_id=uid,
            defaults={'rol': 'RESP', 'asignado_por': usuario})
    dep = TareaDependencia.objects.create(
        predecesora=bloqueante, sucesora=tarea, tipo='FS', origen='BLOQUEO',
        motivo=motivo, creado_por=usuario)
    tarea.estado = 'BLOQ'
    tarea.save(update_fields=['estado'])
    registrar_actividad(tarea, usuario, 'BLOQUEO',
                        detalle=f"Bloqueada · {motivo}. Se creó {bloqueante.folio}.")
    registrar_actividad(bloqueante, usuario, 'CREADA',
                        detalle=f"Tarea bloqueante para desbloquear {tarea.folio}")
    # Retraso estimado por el bloqueo: empuja el fin de la tarea (y su cadena)
    # los días hábiles que se espera dure (desde hoy hasta la fecha compromiso).
    delay = _delay_bloqueo(bloqueante.fecha_inicio_plan, fecha_compromiso)
    if delay:
        _aplicar_delay_bloqueo(dep, tarea, delay, usuario)
    recalcular_tablero(tablero)
    return bloqueante


def resolver_bloqueos_de(bloqueante, usuario):
    """Al completarse una tarea bloqueante, marca resueltos sus bloqueos y saca de
    BLOQ a las tareas que ya no tengan bloqueos pendientes."""
    afectadas = []
    deps = (TareaDependencia.objects
            .filter(predecesora=bloqueante, origen='BLOQUEO', resuelta=False)
            .select_related('sucesora'))
    for d in deps:
        # Ajusta el retraso al REAL (día en que se resolvió vs lo estimado) y
        # recorre la tarea y su cadena en consecuencia.
        resol = bloqueante.fecha_fin_real or timezone.localdate()
        delay_real = _delay_bloqueo(bloqueante.fecha_inicio_plan, resol)
        _aplicar_delay_bloqueo(d, d.sucesora, delay_real, usuario)
        d.resuelta = True
        d.resuelta_en = timezone.now()
        d.save(update_fields=['resuelta', 'resuelta_en'])
        suc = d.sucesora
        pendientes = TareaDependencia.objects.filter(
            sucesora=suc, origen='BLOQUEO', resuelta=False).exists()
        if not pendientes and suc.estado == 'BLOQ':
            suc.estado = 'PROC' if suc.asignaciones.exists() else 'PEND'
            suc.save(update_fields=['estado'])
            # Devuélvela a su estado real: si ya estaban todas las confirmaciones,
            # vuelve a "En revisión"; si no, queda en proceso/pendiente.
            evaluar_cierre(suc)
            registrar_actividad(suc, usuario, 'DESBLOQUEO',
                                detalle=f"Desbloqueada al completar {bloqueante.folio}")
            afectadas.append(suc)
    return afectadas


# --------------------------------------------------------------------------
# Plantillas: instanciar un tablero molde en uno operativo
# --------------------------------------------------------------------------
@transaction.atomic
def instanciar_plantilla(plantilla, *, nombre, fecha_arranque, responsable_id, modo_cierre, usuario):
    """Crea un tablero operativo a partir de una plantilla: copia estructura
    (tareas, jerarquía, orden, pesos, hitos, perfil_sugerido), dependencias
    PLANEADA y recalcula las fechas en días hábiles desde `fecha_arranque`.
    NO copia asignaciones, comentarios, bitácora, bloqueos ni progreso."""
    empresa = plantilla.empresa
    n = Tablero.objects.filter(empresa=empresa).count() + 1
    nuevo = Tablero.objects.create(
        empresa=empresa, codigo=f"TAB-{n:04d}", nombre=nombre.strip(),
        descripcion=plantilla.descripcion, tipo=plantilla.tipo, color=plantilla.color,
        modo_cierre=modo_cierre or plantilla.modo_cierre,
        responsable_id=responsable_id or None, fecha_inicio=fecha_arranque,
        es_plantilla=False, plantilla_origen=plantilla,
        instanciado_en=timezone.now(), creado_por=usuario)

    tareas = list(plantilla.tareas.all())
    starts = [t.fecha_inicio_plan for t in tareas if t.fecha_inicio_plan]
    base = min(starts) if starts else None

    def _recorre(t):
        if not t.fecha_inicio_plan or not base or not fecha_arranque:
            return None, None
        offset = (dias_habiles_entre(base, t.fecha_inicio_plan) or 1) - 1
        n_ini = sumar_dias_habiles(fecha_arranque, max(0, offset))
        if t.es_hito or not t.fecha_fin_plan:
            return n_ini, n_ini
        dur = dias_habiles_entre(t.fecha_inicio_plan, t.fecha_fin_plan) or 1
        return n_ini, sumar_dias_habiles(n_ini, dur - 1)

    mapa = {}
    for t in tareas:
        ni, nf = _recorre(t)
        mapa[t.id] = Tarea.objects.create(
            empresa=empresa, tablero=nuevo, padre=None, es_bloqueante=t.es_bloqueante,
            titulo=t.titulo, descripcion=t.descripcion, folio=siguiente_folio(empresa),
            orden=t.orden, prioridad=t.prioridad, perfil_sugerido=t.perfil_sugerido,
            peso=t.peso, es_hito=t.es_hito, estado='PEND', avance=0,
            fecha_inicio_plan=ni, fecha_fin_plan=nf,
            duracion_dias=(dias_habiles_entre(ni, nf) if ni and nf else None),
            duracion_horas=t.duracion_horas, creado_por=usuario)
    for t in tareas:
        if t.padre_id in mapa:
            hijo = mapa[t.id]
            hijo.padre = mapa[t.padre_id]
            hijo.save(update_fields=['padre'])
    for dep in TareaDependencia.objects.filter(sucesora__tablero=plantilla, origen='PLANEADA'):
        if dep.predecesora_id in mapa and dep.sucesora_id in mapa:
            TareaDependencia.objects.create(
                predecesora=mapa[dep.predecesora_id], sucesora=mapa[dep.sucesora_id],
                tipo=dep.tipo, desfase_dias=dep.desfase_dias, origen='PLANEADA',
                creado_por=usuario)
    recalcular_tablero(nuevo)
    return nuevo


# --------------------------------------------------------------------------
# Alta de tarea
# --------------------------------------------------------------------------
@transaction.atomic
def crear_tarea(*, tablero, usuario, titulo, padre=None, **campos):
    empresa = tablero.empresa
    orden = campos.pop('orden', None)
    if orden is None:
        agg = Tarea.objects.filter(tablero=tablero, padre=padre).aggregate(m=Max('orden'))
        orden = (agg['m'] or 0) + 1
    tarea = Tarea.objects.create(
        empresa=empresa, tablero=tablero, padre=padre, titulo=titulo.strip(),
        folio=siguiente_folio(empresa), orden=orden, creado_por=usuario, **campos)
    recalcular_tablero(tablero)
    registrar_actividad(tarea, usuario, 'CREADA', detalle=f"Tarea creada: {tarea.titulo}")
    tarea.refresh_from_db()
    return tarea
