from django.db import models
from django.contrib.auth.models import User

from admon_empresas.models import Empresa, Sucursal
from admon_inventarios.models import Producto, Lote, NumeroSerie, Ubicacion


class Receta(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    producto_terminado = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name='recetas')
    nombre = models.CharField(max_length=255)
    version = models.CharField(max_length=10, default='1.0')
    descripcion = models.TextField(blank=True, null=True)
    rendimiento = models.DecimalField(max_digits=12, decimal_places=4, default=1,
                                      help_text="Unidades de producto terminado que produce esta receta")
    activa = models.BooleanField(default=True)

    class Meta:
        unique_together = ('producto_terminado', 'version')

    def __str__(self):
        return f"{self.nombre} v{self.version} → {self.producto_terminado.nombre}"


class DetalleReceta(models.Model):
    receta = models.ForeignKey(Receta, related_name='insumos', on_delete=models.CASCADE)
    insumo = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name='usado_en_recetas')
    cantidad_requerida = models.DecimalField(max_digits=12, decimal_places=4)
    es_opcional = models.BooleanField(default=False)
    notas = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"{self.insumo.sku} x{self.cantidad_requerida}"


class OrdenProduccion(models.Model):
    ESTADO_CHOICES = [
        ('ABIERTA', 'Abierta'),
        ('EN_PROCESO', 'En proceso'),
        ('PAUSADA', 'Pausada'),
        ('COMPLETADA', 'Completada'),
        ('CANCELADA', 'Cancelada'),
    ]

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    sucursal = models.ForeignKey(Sucursal, on_delete=models.PROTECT)
    folio = models.CharField(max_length=20, blank=True)
    receta = models.ForeignKey(Receta, on_delete=models.PROTECT)
    cantidad_a_producir = models.DecimalField(max_digits=12, decimal_places=4)
    cantidad_producida = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES, default='ABIERTA')

    responsable = models.ForeignKey(User, on_delete=models.PROTECT)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_inicio = models.DateTimeField(null=True, blank=True)
    fecha_fin = models.DateTimeField(null=True, blank=True)
    notas = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-fecha_creacion']
        verbose_name_plural = "Órdenes de producción"

    def save(self, *args, **kwargs):
        if not self.folio:
            ultimo = OrdenProduccion.objects.filter(empresa=self.empresa).count() + 1
            self.folio = f"OP-{ultimo:05d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.folio}: {self.receta.producto_terminado.nombre} x{self.cantidad_a_producir} [{self.estado}]"


class ConsumoProduccion(models.Model):
    """Insumos realmente consumidos (con su lote/serie) en una orden."""
    orden = models.ForeignKey(OrdenProduccion, related_name='consumos', on_delete=models.CASCADE)
    insumo = models.ForeignKey(Producto, on_delete=models.PROTECT)
    lote = models.ForeignKey(Lote, on_delete=models.PROTECT, null=True, blank=True)
    serie = models.ForeignKey(NumeroSerie, on_delete=models.PROTECT, null=True, blank=True)
    ubicacion = models.ForeignKey(Ubicacion, on_delete=models.PROTECT)
    cantidad_consumida = models.DecimalField(max_digits=12, decimal_places=4)
