import decimal

from django.db import models
from django.conf import settings

from admon_empresas.models import Empresa, Moneda, Sucursal


class Proveedor(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='proveedores')

    # Visibilidad: vacío = global a la empresa / con datos = solo esas sucursales
    sucursales_acceso = models.ManyToManyField(
        Sucursal, blank=True, related_name='proveedores_permitidos')

    nombre_fiscal = models.CharField(max_length=255)
    nombre_comercial = models.CharField(max_length=255, blank=True, null=True)
    rfc = models.CharField(max_length=15, verbose_name="RFC / Tax ID")

    email = models.EmailField(blank=True, null=True)
    telefono = models.CharField(max_length=20, blank=True)
    celular = models.CharField(max_length=20, blank=True)
    direccion = models.CharField(max_length=255, blank=True)
    contacto_nombre = models.CharField(max_length=100, blank=True, verbose_name="Atención con")

    moneda_predeterminada = models.ForeignKey(Moneda, on_delete=models.SET_NULL, null=True, blank=True)
    dias_credito = models.PositiveIntegerField(default=0, verbose_name="Días de crédito")

    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Proveedor"
        verbose_name_plural = "Proveedores"
        ordering = ['nombre_fiscal']

    def __str__(self):
        return self.nombre_comercial or self.nombre_fiscal


class AutorizadorCompra(models.Model):
    """Define el límite de autorización y el supervisor de un usuario,
    por empresa. La OC escala por esta cadena hasta encontrar quien la cubra."""
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='autorizadores_compra')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='autorizaciones_compra')

    monto_autorizado = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text="Monto máximo que puede autorizar. 0 = sin límite (cima de la cadena).")
    supervisor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='subordinados_compra',
        help_text="A quién escala cuando el monto supera su límite.")

    activo = models.BooleanField(default=True)

    class Meta:
        unique_together = ('empresa', 'usuario')
        verbose_name = "Autorizador de compras"
        verbose_name_plural = "Autorizadores de compras"

    @property
    def sin_limite(self):
        return self.monto_autorizado == 0

    def cubre(self, monto):
        """¿Este autorizador puede aprobar el monto dado?"""
        return self.sin_limite or decimal.Decimal(monto) <= self.monto_autorizado

    def __str__(self):
        tope = "sin límite" if self.sin_limite else f"${self.monto_autorizado:,.2f}"
        return f"{self.usuario.username} ({tope})"


class OrdenCompra(models.Model):
    ESTADO_CHOICES = [
        ('BORRADOR', 'Borrador'),
        ('SOLICITADO', 'En autorización'),
        ('AUTORIZADO', 'Autorizado'),
        ('RECIBIDO', 'Recibido parcial'),
        ('FINALIZADO', 'Finalizado'),
        ('RECHAZADO', 'Rechazado'),
        ('CANCELADO', 'Cancelado'),
    ]

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    sucursal_destino = models.ForeignKey(Sucursal, on_delete=models.CASCADE, related_name='ordenes_compra')
    proveedor = models.ForeignKey(Proveedor, on_delete=models.PROTECT)
    moneda = models.ForeignKey(Moneda, on_delete=models.PROTECT)

    folio = models.CharField(max_length=40, unique=True)
    consecutivo = models.IntegerField(default=0)
    fecha_emision = models.DateField(auto_now_add=True)
    fecha_entrega_estimada = models.DateField(null=True, blank=True)

    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='BORRADOR')
    notas = models.TextField(blank=True)
    # Compra de uso personal (no afecta reportes de la comercializadora)
    uso_personal = models.BooleanField(default=False)

    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    impuestos = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='ordenes_creadas')

    # Autorización por cadena de supervisión
    autorizador_actual = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='ordenes_por_autorizar',
        help_text="Quién tiene la OC para firmar en este momento.")
    fecha_solicitud = models.DateTimeField(null=True, blank=True)
    fecha_autorizacion = models.DateTimeField(null=True, blank=True)

    motivo_rechazo = models.TextField(blank=True, null=True)

    # Cancelación
    fecha_cancelacion = models.DateTimeField(null=True, blank=True)
    usuario_cancelacion = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='ordenes_canceladas')
    motivo_cancelacion = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ['-fecha_emision', '-id']
        verbose_name = "Orden de compra"
        verbose_name_plural = "Órdenes de compra"

    @property
    def total_recibido_pct(self):
        partidas = list(self.detalles.all())
        if not partidas:
            return 0
        pedido = sum(d.cantidad_pedida for d in partidas)
        recibido = sum(d.cantidad_recibida for d in partidas)
        return float(recibido / pedido * 100) if pedido else 0

    @property
    def esta_recibida_completa(self):
        return all(d.cantidad_recibida >= d.cantidad_pedida for d in self.detalles.all())

    def color_estado(self):
        return {
            'BORRADOR': 'amber', 'SOLICITADO': 'blue', 'AUTORIZADO': 'indigo',
            'RECIBIDO': 'cyan', 'FINALIZADO': 'emerald', 'RECHAZADO': 'rose',
            'CANCELADO': 'slate',
        }.get(self.estado, 'slate')

    def __str__(self):
        return f"{self.folio} - {self.proveedor}"


class DetalleOrdenCompra(models.Model):
    orden = models.ForeignKey(OrdenCompra, related_name='detalles', on_delete=models.CASCADE)
    producto = models.ForeignKey('admon_inventarios.Producto', on_delete=models.PROTECT)
    cantidad_pedida = models.DecimalField(max_digits=12, decimal_places=4)
    cantidad_recibida = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    precio_unitario = models.DecimalField(max_digits=14, decimal_places=4)
    # Impuesto aplicado (FK al catálogo) + snapshot de la tasa al momento de la OC
    impuesto = models.ForeignKey(
        'admon_empresas.Impuesto', on_delete=models.SET_NULL, null=True, blank=True)
    iva_porcentaje = models.DecimalField(max_digits=7, decimal_places=4, default=16)
    es_retencion = models.BooleanField(default=False)

    @property
    def pendiente_por_recibir(self):
        restante = self.cantidad_pedida - self.cantidad_recibida
        return restante if restante > 0 else decimal.Decimal('0')

    @property
    def importe(self):
        return self.cantidad_pedida * self.precio_unitario

    def __str__(self):
        return f"{self.producto.sku} x{self.cantidad_pedida}"


class AutorizacionOC(models.Model):
    """Cada firma que recolecta una OC al subir por la cadena de supervisión."""
    ACCION_CHOICES = [
        ('APROBADO', 'Aprobado'),
        ('RECHAZADO', 'Rechazado'),
    ]
    orden = models.ForeignKey(OrdenCompra, related_name='autorizaciones', on_delete=models.CASCADE)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    secuencia = models.PositiveIntegerField(default=1)
    accion = models.CharField(max_length=10, choices=ACCION_CHOICES)
    es_final = models.BooleanField(default=False, help_text="True si esta firma cerró la autorización.")
    comentario = models.TextField(blank=True, null=True)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['secuencia']

    def __str__(self):
        return f"{self.orden.folio}: {self.usuario.username} {self.accion}"
