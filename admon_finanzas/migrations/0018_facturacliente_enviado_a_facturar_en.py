from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('admon_finanzas', '0017_pago_complemento_enviado_en'),
    ]

    operations = [
        migrations.AddField(
            model_name='facturacliente',
            name='enviado_a_facturar_en',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
