"""
Siembra un tablero-demo para PH Analytics: la historia de vida de un contrato
La Nogalera → Costco por 1,000 lb de nuez, en 2 releases (500 lb c/u), con
planeación, producción, calidad, etiquetado, logística, embarque marítimo con
avisos de naviera cada 5 días y entrega. Release 1 sale limpio; Release 2 trae
incidencias (producción tarde, bloqueo de calidad, etiquetado/logística
atrasados) y queda reprogramado vs su línea base.

Uso (en el droplet):
    docker compose -f docker-compose.prod.yml exec web python manage.py seed_demo_nogalera

Es idempotente: borra el tablero demo anterior (código DEMO-COSTCO) y lo recrea.
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from admon_empresas.models import Empresa, EmpresaModulo, AccesoModuloUsuario
from admon_tareas.models import Tablero, Tarea, TareaAsignacion, TareaDependencia
from admon_tareas import services


class Command(BaseCommand):
    help = "Crea un tablero demo (contrato Costco · nuez) para PH Analytics."

    @transaction.atomic
    def handle(self, *args, **opts):
        from django.contrib.auth import get_user_model
        User = get_user_model()

        empresa = (Empresa.objects.filter(nombre_fiscal__icontains='analytics').first()
                   or Empresa.objects.filter(nombre_fiscal__icontains='PH').first())
        if not empresa:
            raise CommandError("No encontré la empresa PH Analytics.")
        self.stdout.write(f"Empresa: {empresa.nombre_fiscal} (id {empresa.id})")

        # Asegura módulo 'tareas' contratado
        EmpresaModulo.objects.update_or_create(
            empresa=empresa, modulo='tareas', defaults={'activo': True})

        matriz = empresa.sucursales.filter(es_matriz=True).first() or empresa.sucursales.first()

        def demo_user(username, nombre):
            u, creado = User.objects.get_or_create(
                username=username, defaults={'first_name': nombre,
                                             'email': f'{username}@nogalera.demo'})
            if creado:
                u.set_password('demo1234')
                u.save()
            p = u.perfil
            p.empresas.add(empresa)
            if not p.empresa_default:
                p.empresa_default = empresa
            if matriz:
                p.sucursales.add(matriz)
                if not p.sucursal_defecto:
                    p.sucursal_defecto = matriz
            if hasattr(p, 'invitacion_aceptada'):
                p.invitacion_aceptada = True
            p.save()
            AccesoModuloUsuario.objects.get_or_create(usuario=u, empresa=empresa, modulo='tareas')
            return u

        comercial = demo_user('demo_comercial', 'Comercial')
        planeacion = demo_user('demo_planeacion', 'Planeación')
        produccion = demo_user('demo_produccion', 'Producción')
        calidad = demo_user('demo_calidad', 'Calidad')
        logistica = demo_user('demo_logistica', 'Logística')
        naviera = demo_user('demo_naviera', 'Tráfico/Naviera')

        # Tablero demo (borra el anterior para reproducibilidad)
        Tablero.objects.filter(empresa=empresa, codigo='DEMO-COSTCO').delete()
        B = Tablero.objects.create(
            empresa=empresa, codigo='DEMO-COSTCO',
            nombre='Contrato Costco · 1,000 lb de nuez (2 releases)',
            descripcion='Historia de vida del contrato La Nogalera → Costco: dos releases '
                        'de 500 lb, de la planeación a la entrega, con incidencias reales.',
            modo_cierre='RESPONSABLE', visibilidad='TODO',
            responsable=comercial, creado_por=comercial,
            color='#0ea5e9')

        def T(padre, titulo, ini=None, fin=None, estado='PEND', avance=0, hito=False,
              etapa=False, prioridad='MEDIA', fin_real=None, asign=None):
            campos = dict(prioridad=prioridad, es_hito=hito, es_etapa=etapa,
                          estado=estado, avance=avance)
            if ini:
                campos['fecha_inicio_plan'] = ini
            if fin:
                campos['fecha_fin_plan'] = fin
            if fin_real:
                campos['fecha_fin_real'] = fin_real
            t = services.crear_tarea(tablero=B, usuario=comercial, titulo=titulo,
                                     padre=padre, **campos)
            for (u, rol) in (asign or []):
                TareaAsignacion.objects.get_or_create(
                    tarea=t, usuario=u, defaults={'rol': rol, 'asignado_por': comercial})
            return t

        def dep(pred, suc, tipo='FS', lag=0):
            TareaDependencia.objects.create(
                predecesora=pred, sucesora=suc, tipo=tipo, desfase_dias=lag,
                origen='PLANEADA', creado_por=comercial)

        d = date

        # ── Detonante: contrato firmado ──────────────────────────────────────
        contrato = T(None, 'Contrato firmado · 1,000 lb de nuez (Costco)',
                     d(2026, 6, 2), d(2026, 6, 2), estado='COMP', avance=100, hito=True,
                     prioridad='ALTA', fin_real=d(2026, 6, 2),
                     asign=[(comercial, 'RESP')])

        def release(nombre, base, delayed=False):
            """Crea una etapa Release con su cadena de fases. base = dict de fechas."""
            et = T(None, nombre, etapa=True)
            plan = T(et, 'Planeación de producción', *base['plan'],
                     estado='COMP', avance=100, fin_real=base['plan'][1],
                     asign=[(planeacion, 'RESP'), (comercial, 'COLA')])
            prod = T(et, 'Producción (descascarado y selección)', *base['prod'],
                     estado=base['prod_estado'], avance=base['prod_avance'],
                     fin_real=base.get('prod_real'), prioridad='ALTA',
                     asign=[(produccion, 'RESP')])
            cal = T(et, 'Control de calidad (humedad, aflatoxinas, calibre)', *base['cal'],
                    estado=base['cal_estado'], avance=base['cal_avance'],
                    fin_real=base.get('cal_real'), prioridad='ALTA',
                    asign=[(calidad, 'RESP')])
            etiq = T(et, 'Etiquetado y empaque (spec Costco)', *base['etiq'],
                     estado=base['etiq_estado'], avance=base['etiq_avance'],
                     fin_real=base.get('etiq_real'),
                     asign=[(logistica, 'RESP'), (calidad, 'COLA')])
            log = T(et, 'Logística y consolidación de contenedor', *base['log'],
                    estado=base['log_estado'], avance=base['log_avance'],
                    fin_real=base.get('log_real'),
                    asign=[(logistica, 'RESP')])
            emb = T(et, 'Embarque marítimo (Manzanillo → Long Beach)', *base['emb'],
                    estado=base['emb_estado'], avance=base['emb_avance'],
                    prioridad='ALTA', asign=[(naviera, 'RESP'), (logistica, 'COLA')])
            # Avisos de la naviera cada 5 días (hitos)
            for etq, fh in base['avisos']:
                comp = (not delayed) and fh <= base['hoy_ref']
                T(emb, etq, fh, fh, estado=('COMP' if comp else 'PEND'),
                  avance=(100 if comp else 0), hito=True, asign=[(naviera, 'RESP')])
            ent = T(et, 'Entrega a Costco (CEDIS)', base['ent'], base['ent'],
                    estado=base['ent_estado'], avance=base['ent_avance'], hito=True,
                    prioridad='ALTA', asign=[(comercial, 'RESP'), (logistica, 'COLA')])
            # Dependencias FS de la cadena
            dep(contrato, plan)
            dep(plan, prod)
            dep(prod, cal)
            dep(cal, etiq)
            dep(etiq, log)
            dep(log, emb)
            dep(emb, ent)
            return dict(et=et, plan=plan, prod=prod, cal=cal, etiq=etiq, log=log,
                        emb=emb, ent=ent)

        hoy_ref = d(2026, 8, 17)

        # ── Release 1: limpio, entregado a tiempo ────────────────────────────
        r1 = release('Release 1 · 500 lb (entregado)', {
            'hoy_ref': hoy_ref,
            'plan': (d(2026, 6, 3), d(2026, 6, 5)),
            'prod': (d(2026, 6, 8), d(2026, 6, 19)), 'prod_estado': 'COMP', 'prod_avance': 100, 'prod_real': d(2026, 6, 19),
            'cal': (d(2026, 6, 22), d(2026, 6, 24)), 'cal_estado': 'COMP', 'cal_avance': 100, 'cal_real': d(2026, 6, 24),
            'etiq': (d(2026, 6, 25), d(2026, 6, 26)), 'etiq_estado': 'COMP', 'etiq_avance': 100, 'etiq_real': d(2026, 6, 26),
            'log': (d(2026, 6, 29), d(2026, 6, 30)), 'log_estado': 'COMP', 'log_avance': 100, 'log_real': d(2026, 6, 30),
            'emb': (d(2026, 7, 1), d(2026, 7, 24)), 'emb_estado': 'COMP', 'emb_avance': 100,
            'avisos': [
                ('Zarpe · ETD Manzanillo', d(2026, 7, 1)),
                ('Aviso naviera +5 días', d(2026, 7, 6)),
                ('Aviso naviera +10 días', d(2026, 7, 11)),
                ('Aviso naviera +15 días', d(2026, 7, 16)),
                ('Aviso naviera +20 días', d(2026, 7, 21)),
                ('Arribo · ETA Long Beach', d(2026, 7, 24)),
            ],
            'ent': d(2026, 7, 27), 'ent_estado': 'COMP', 'ent_avance': 100,
        })

        # ── Release 2: con incidencias ───────────────────────────────────────
        r2 = release('Release 2 · 500 lb (con incidencias)', {
            'hoy_ref': hoy_ref,
            'plan': (d(2026, 7, 6), d(2026, 7, 8)),
            # Producción terminó TARDE (falta de materia prima)
            'prod': (d(2026, 7, 13), d(2026, 7, 24)), 'prod_estado': 'COMP', 'prod_avance': 100, 'prod_real': d(2026, 8, 1),
            # Calidad se BLOQUEA (lote fuera de spec) — se marca abajo con services.bloquear
            'cal': (d(2026, 7, 27), d(2026, 7, 29)), 'cal_estado': 'PEND', 'cal_avance': 20,
            'etiq': (d(2026, 8, 3), d(2026, 8, 5)), 'etiq_estado': 'PEND', 'etiq_avance': 0,
            'log': (d(2026, 8, 6), d(2026, 8, 7)), 'log_estado': 'PEND', 'log_avance': 0,
            'emb': (d(2026, 8, 12), d(2026, 9, 4)), 'emb_estado': 'PEND', 'emb_avance': 0,
            'avisos': [
                ('Zarpe · ETD Manzanillo', d(2026, 8, 12)),
                ('Aviso naviera +5 días', d(2026, 8, 17)),
                ('Aviso naviera +10 días', d(2026, 8, 22)),
                ('Aviso naviera +15 días', d(2026, 8, 27)),
                ('Aviso naviera +20 días', d(2026, 9, 1)),
                ('Arribo · ETA Long Beach', d(2026, 9, 4)),
            ],
            'ent': d(2026, 9, 7), 'ent_estado': 'PEND', 'ent_avance': 0,
        }, delayed=True)

        # Bloqueo real de calidad en Release 2
        services.bloquear(
            tarea=r2['cal'], usuario=calidad,
            motivo='Lote fuera de especificación: humedad 6.8% (máx 5%). Segregar y re-muestrear.',
            titulo='Reproceso: secado y re-muestreo del lote R2',
            asignados_ids=[calidad.id, produccion.id],
            fecha_compromiso=d(2026, 8, 20))

        # Recalcula (WBS, avance de etapas, rollup de fechas)
        services.recalcular_tablero(B)

        # Línea base ORIGINAL (antes de las incidencias): entrega planeada ~24/08.
        # El actual quedó al 07/09 → el tablero muestra "Reprogramado +14d".
        B.fecha_fin_base = d(2026, 8, 24)
        B.fecha_inicio = d(2026, 6, 2)
        B.fecha_fin = d(2026, 9, 7)
        B.save(update_fields=['fecha_fin_base', 'fecha_inicio', 'fecha_fin'])

        n = Tarea.objects.filter(tablero=B).count()
        self.stdout.write(self.style.SUCCESS(
            f"OK · Tablero '{B.nombre}' creado con {n} tareas. "
            f"Responsables demo: comercial/planeacion/produccion/calidad/logistica/naviera "
            f"(contraseña demo1234). Ábrelo en Tareas → Tableros."))
