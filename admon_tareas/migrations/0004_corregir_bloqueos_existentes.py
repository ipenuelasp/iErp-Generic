"""
Corrección retroactiva de los bloqueos ya existentes: aplica a cada tarea
bloqueada el retraso que le hubiera tocado por su bloqueo (según el periodo del
bloqueante), para que las fechas y el 'split' del Gantt reflejen la pausa.

Idempotente: usa dep.desfase_dias como marca de lo ya aplicado, así que si ya se
corrigió, no vuelve a mover nada. En una BD nueva (sin bloqueos) es un no-op.
"""
from django.db import migrations


def corregir(apps, schema_editor):
    # Se usan los servicios/modelos reales: en este punto el esquema coincide.
    from admon_tareas import services
    from admon_tareas.models import TareaDependencia

    deps = (TareaDependencia.objects.filter(origen='BLOQUEO')
            .select_related('predecesora', 'sucesora'))
    for dep in deps:
        try:
            b = dep.predecesora
            resol = (b.fecha_fin_real or b.fecha_fin_plan) if b.estado == 'COMP' \
                else b.fecha_fin_plan
            delay = services._delay_bloqueo(b.fecha_inicio_plan, resol)
            if delay and (dep.desfase_dias or 0) != delay:
                services._aplicar_delay_bloqueo(dep, dep.sucesora, delay, None)
        except Exception as e:   # una fila mala no debe tumbar la migración
            print(f"[corregir_bloqueos] dep {dep.id}: {e}")


def revertir(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('admon_tareas', '0003_alter_tareadependencia_tipo'),
    ]

    operations = [
        migrations.RunPython(corregir, revertir),
    ]
