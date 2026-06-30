from django.db import migrations
from django.db.models import F


def backfill_subtotal(apps, schema_editor):
    """Los CFDI creados antes de tener desglose quedaron con subtotal=0.
    Para no marcarlos como 'parciales', usamos su total como base."""
    CfdiCliente = apps.get_model('admon_finanzas', 'CfdiCliente')
    CfdiCliente.objects.filter(subtotal=0, total__gt=0).update(subtotal=F('total'))


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('admon_finanzas', '0010_cfdicliente_retenciones_cfdicliente_subtotal_and_more'),
    ]
    operations = [
        migrations.RunPython(backfill_subtotal, noop),
    ]
