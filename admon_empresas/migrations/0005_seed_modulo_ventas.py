from django.db import migrations


def sembrar_ventas(apps, schema_editor):
    Empresa = apps.get_model('admon_empresas', 'Empresa')
    EmpresaModulo = apps.get_model('admon_empresas', 'EmpresaModulo')
    for empresa in Empresa.objects.all():
        EmpresaModulo.objects.get_or_create(
            empresa=empresa, modulo='ventas', defaults={'activo': True})


def revertir(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('admon_empresas', '0004_seed_modulos_empresas'),
    ]
    operations = [
        migrations.RunPython(sembrar_ventas, revertir),
    ]
