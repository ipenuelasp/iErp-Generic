from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('admon_empresas', '0010_empresa_email_contador'),
    ]

    operations = [
        migrations.AddField(
            model_name='perfilusuario',
            name='foto',
            field=models.ImageField(blank=True, help_text='Foto de perfil del usuario.', null=True, upload_to='usuarios/fotos/'),
        ),
    ]
