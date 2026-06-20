from django.db import migrations


def sembrar_modulos(apps, schema_editor):
    Empresa = apps.get_model('admon_empresas', 'Empresa')
    EmpresaModulo = apps.get_model('admon_empresas', 'EmpresaModulo')
    # Mismas claves que admon_empresas.modulos.MODULOS_DISPONIBLES
    claves = ['inventarios', 'kits', 'produccion', 'compras', 'finanzas']
    for empresa in Empresa.objects.all():
        for clave in claves:
            EmpresaModulo.objects.get_or_create(
                empresa=empresa, modulo=clave, defaults={'activo': True})


def revertir(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('admon_empresas', '0003_accesomodulousuario_empresamodulo'),
    ]
    operations = [
        migrations.RunPython(sembrar_modulos, revertir),
    ]
