"""
Vertical de cirugías (Insermed). Agrega la capa clínica (doctores, hospitales,
solicitud de cirugía) y se conecta al motor genérico:
  Solicitud → Surtir (SalidaKit de inventarios) → Regreso → Liquidación (Pedido de ventas).
Dependencia unidireccional: este módulo importa de inventarios/ventas, nunca al revés.
"""
from django.db import models
from django.conf import settings

from admon_empresas.models import Empresa, Sucursal


class Hospital(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='hospitales')
    codigo = models.CharField(max_length=20, blank=True)
    nombre = models.CharField(max_length=255)
    ciudad = models.CharField(max_length=120, blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Hospital"
        verbose_name_plural = "Hospitales"
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Doctor(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='doctores')
    nombre = models.CharField(max_length=255)
    email = models.EmailField(blank=True, null=True)
    telefono = models.CharField(max_length=30, blank=True)
    celular = models.CharField(max_length=30, blank=True)
    direccion = models.CharField(max_length=255, blank=True)
    rfc = models.CharField(max_length=15, blank=True)
    razon_social = models.CharField(max_length=255, blank=True)
    cedula = models.CharField(max_length=30, blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Doctor"
        verbose_name_plural = "Doctores"
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class SolicitudCirugia(models.Model):
    """Orquesta el flujo de una cirugía y lo conecta con el motor genérico."""
    ESTADO_CHOICES = [
        ('SOLICITADA', 'Solicitada'),
        ('SURTIDA', 'Surtida (material enviado)'),
        ('RETORNADA', 'Regresada (pendiente de finalizar)'),
        ('POR_FACTURAR', 'Por facturar (finalizada, pendiente de pedido)'),
        ('LIQUIDADA', 'Liquidada (pedido generado)'),
        ('CANCELADA', 'Cancelada'),
    ]

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    sucursal = models.ForeignKey(Sucursal, on_delete=models.PROTECT, related_name='cirugias')
    folio = models.CharField(max_length=25, unique=True)
    consecutivo = models.IntegerField(default=0)

    # Datos clínicos
    paciente = models.CharField(max_length=255, blank=True,
                                help_text="Referencia del paciente (no datos sensibles)")
    doctor = models.ForeignKey(Doctor, on_delete=models.PROTECT, null=True, blank=True)
    hospital = models.ForeignKey(Hospital, on_delete=models.PROTECT, null=True, blank=True)
    fecha_cirugia = models.DateField(null=True, blank=True)

    # A quién se le factura al liquidar (cliente del módulo de ventas)
    cliente = models.ForeignKey('admon_ventas.Cliente', on_delete=models.PROTECT, null=True, blank=True)

    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default='SOLICITADA')
    comentario = models.TextField(blank=True, null=True)

    # Conexión con el motor genérico (cirugías -> inventarios, sin ciclos)
    salidas = models.ManyToManyField('admon_inventarios.SalidaKit', blank=True,
                                     related_name='solicitudes_cirugia')
    pedido = models.ForeignKey('admon_ventas.Pedido', on_delete=models.SET_NULL,
                               null=True, blank=True, related_name='cirugias')

    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   related_name='cirugias_creadas')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_cirugia', '-id']
        verbose_name = "Solicitud de cirugía"
        verbose_name_plural = "Solicitudes de cirugía"

    def color_estado(self):
        return {'SOLICITADA': 'amber', 'SURTIDA': 'blue', 'RETORNADA': 'purple',
                'POR_FACTURAR': 'fuchsia', 'LIQUIDADA': 'emerald',
                'CANCELADA': 'slate'}.get(self.estado, 'slate')

    def __str__(self):
        return f"{self.folio} — {self.paciente or 's/paciente'}"


class SueltoCirugia(models.Model):
    """Producto individual (fuera de caja) agregado al borrador de una cirugía.
    Es solo la línea planeada: al surtir se descuenta del stock general de la
    sucursal y se convierte en el contenido de una salida de 'material suelto'.
    Se elimina en cuanto se surte."""
    solicitud = models.ForeignKey(SolicitudCirugia, related_name='sueltos',
                                  on_delete=models.CASCADE)
    producto = models.ForeignKey('admon_inventarios.Producto', on_delete=models.PROTECT)
    cantidad = models.DecimalField(max_digits=12, decimal_places=4)
    # Existencia elegida a mano (serie exacta) o indicada (lote/ubicación) para que
    # el almacén saque físicamente la correcta. Si van en null, el surtido asigna
    # por FIFO (stock simple sin lote/serie).
    lote = models.ForeignKey('admon_inventarios.Lote', on_delete=models.PROTECT,
                             null=True, blank=True)
    serie = models.ForeignKey('admon_inventarios.NumeroSerie', on_delete=models.PROTECT,
                              null=True, blank=True)
    ubicacion = models.ForeignKey('admon_inventarios.Ubicacion', on_delete=models.PROTECT,
                                  null=True, blank=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']
        verbose_name = "Material suelto de cirugía"
        verbose_name_plural = "Material suelto de cirugía"

    def __str__(self):
        return f"{self.solicitud.folio}: {self.producto.sku} x{self.cantidad}"
