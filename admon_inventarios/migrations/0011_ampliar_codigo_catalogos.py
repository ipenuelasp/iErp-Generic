from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('admon_inventarios', '0010_instanciakit_caja_contenedora'),
    ]

    operations = [
        migrations.AlterField(
            model_name='clase',
            name='codigo',
            field=models.CharField(max_length=20),
        ),
        migrations.AlterField(
            model_name='grupo',
            name='codigo',
            field=models.CharField(max_length=20),
        ),
        migrations.AlterField(
            model_name='tipo',
            name='codigo',
            field=models.CharField(max_length=20),
        ),
    ]
