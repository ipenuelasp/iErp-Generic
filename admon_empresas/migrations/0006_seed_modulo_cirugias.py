from django.db import migrations


def sembrar_cirugias(apps, schema_editor):
    """Cirugías es vertical y se apoya en Kits; se habilita solo donde Kits está activo."""
    EmpresaModulo = apps.get_model('admon_empresas', 'EmpresaModulo')
    empresas_con_kits = EmpresaModulo.objects.filter(
        modulo='kits', activo=True).values_list('empresa_id', flat=True)
    for emp_id in empresas_con_kits:
        EmpresaModulo.objects.get_or_create(
            empresa_id=emp_id, modulo='cirugias', defaults={'activo': True})


def revertir(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('admon_empresas', '0005_seed_modulo_ventas'),
    ]
    operations = [
        migrations.RunPython(sembrar_cirugias, revertir),
    ]
