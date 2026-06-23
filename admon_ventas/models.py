import decimal

from django.db import models
from django.conf import settings

from admon_empresas.models import Empresa, Moneda, Sucursal


class Cliente(models.Model):
    """Cliente al que la empresa vende. Visibilidad global o por sucursales
    (mismo patrón que Proveedor en compras)."""
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='clientes')

    # Visibilidad: vacío = global a la empresa / con datos = solo esas sucursales
    sucursales_acceso = models.ManyToManyField(
        Sucursal, blank=True, related_name='clientes_permitidos')

    nombre_fiscal = models.CharField(max_length=255)
    nombre_comercial = models.CharField(max_length=255, blank=True, null=True)
    rfc = models.CharField(max_length=15, verbose_name="RFC / Tax ID", blank=True)

    email = models.EmailField(blank=True, null=True)
    telefono = models.CharField(max_length=20, blank=True)
    contacto_nombre = models.CharField(max_length=100, blank=True, verbose_name="Atención con")
    direccion = models.CharField(max_length=255, blank=True)
    codigo_postal = models.CharField(max_length=10, blank=True, verbose_name="Código postal")
    regimen_fiscal = models.CharField(max_length=255, blank=True, verbose_name="Régimen fiscal")

    # Constancia de Situación Fiscal (SAT) adjunta
    constancia_fiscal = models.FileField(upload_to='constancias/', null=True, blank=True,
                                         verbose_name="Constancia de situación fiscal")

    moneda_predeterminada = models.ForeignKey(Moneda, on_delete=models.SET_NULL, null=True, blank=True)
    dias_credito = models.PositiveIntegerField(default=0, verbose_name="Días de crédito")
    limite_credito = models.DecimalField(max_digits=14, decimal_places=2, default=0,
                                         help_text="0 = sin límite")

    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"
        ordering = ['nombre_fiscal']

    def __str__(self):
        return self.nombre_comercial or self.nombre_fiscal


class Pedido(models.Model):
    """Pedido de venta. Flujo: BORRADOR → CONFIRMADO → (ENTREGADO_PARCIAL) →
    ENTREGADO. Al entregar descuenta inventario y genera la cuenta por cobrar."""
    ESTADO_CHOICES = [
        ('BORRADOR', 'Borrador'),
        ('CONFIRMADO', 'Confirmado'),
        ('ENTREGADO_PARCIAL', 'Entregado parcial'),
        ('ENTREGADO', 'Entregado'),
        ('CANCELADO', 'Cancelado'),
    ]

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    sucursal = models.ForeignKey(Sucursal, on_delete=models.CASCADE, related_name='pedidos')
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='pedidos')
    moneda = models.ForeignKey(Moneda, on_delete=models.PROTECT)

    folio = models.CharField(max_length=25, unique=True)
    consecutivo = models.IntegerField(default=0)
    fecha_emision = models.DateField(auto_now_add=True)
    fecha_entrega_estimada = models.DateField(null=True, blank=True)

    ORIGEN_CHOICES = [
        ('MANUAL', 'Manual'),
        ('COTIZACION', 'Desde cotización'),
        ('CIRUGIA', 'Liquidación de cirugía/kit'),
    ]

    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='BORRADOR')
    origen = models.CharField(max_length=12, choices=ORIGEN_CHOICES, default='MANUAL')
    genera_cxc = models.BooleanField(default=True, help_text="Genera cuenta por cobrar al entregar")
    notas = models.TextField(blank=True)

    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    impuestos = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='pedidos_creados')

    fecha_cancelacion = models.DateTimeField(null=True, blank=True)
    motivo_cancelacion = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ['-fecha_emision', '-id']
        verbose_name = "Pedido de venta"
        verbose_name_plural = "Pedidos de venta"

    @property
    def total_entregado_pct(self):
        partidas = list(self.detalles.all())
        if not partidas:
            return 0
        pedido = sum(d.cantidad for d in partidas)
        entregado = sum(d.cantidad_entregada for d in partidas)
        return float(entregado / pedido * 100) if pedido else 0

    @property
    def esta_entregado_completo(self):
        dets = list(self.detalles.all())
        return bool(dets) and all(d.cantidad_entregada >= d.cantidad for d in dets)

    def color_estado(self):
        return {
            'BORRADOR': 'amber', 'CONFIRMADO': 'blue', 'ENTREGADO_PARCIAL': 'cyan',
            'ENTREGADO': 'emerald', 'CANCELADO': 'slate',
        }.get(self.estado, 'slate')

    def __str__(self):
        return f"{self.folio} - {self.cliente}"


class DetallePedido(models.Model):
    LINEA_PRODUCTO = 'PRODUCTO'
    LINEA_RENTA = 'RENTA'
    LINEA_CHOICES = [
        (LINEA_PRODUCTO, 'Producto / consumible'),
        (LINEA_RENTA, 'Renta de equipo'),
    ]

    pedido = models.ForeignKey(Pedido, related_name='detalles', on_delete=models.CASCADE)
    producto = models.ForeignKey('admon_inventarios.Producto', on_delete=models.PROTECT)
    tipo_linea = models.CharField(max_length=10, choices=LINEA_CHOICES, default=LINEA_PRODUCTO)
    cantidad = models.DecimalField(max_digits=12, decimal_places=4)
    cantidad_entregada = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    precio_unitario = models.DecimalField(max_digits=14, decimal_places=4)
    # Margen financiero usado en esta partida (% sobre venta). Solo informativo:
    # el precio_unitario es el que manda. Nulo en partidas sin margen (renta/kit).
    margen = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    # Impuesto aplicado (FK al catálogo) + snapshot de la tasa al momento del pedido
    impuesto = models.ForeignKey(
        'admon_empresas.Impuesto', on_delete=models.SET_NULL, null=True, blank=True)
    iva_porcentaje = models.DecimalField(max_digits=7, decimal_places=4, default=16)
    es_retencion = models.BooleanField(default=False)
    # Extra ("gol"): línea agregada al pedido que NO proviene de la solicitud/regreso
    # de la cirugía (no movió inventario por el flujo de kit). Indicador interno.
    es_extra = models.BooleanField(default=False,
                                   help_text="Producto agregado al pedido fuera del flujo de cirugía")

    @property
    def pendiente_por_entregar(self):
        restante = self.cantidad - self.cantidad_entregada
        return restante if restante > 0 else decimal.Decimal('0')

    @property
    def importe(self):
        return self.cantidad * self.precio_unitario

    def __str__(self):
        return f"{self.producto.sku} x{self.cantidad}"


class ComisionPedido(models.Model):
    """Comisión interna ligada a un pedido (técnico, doctor, etc.).
    Afecta la rentabilidad pero NO se muestra en el documento al cliente."""
    TIPO_CHOICES = [
        ('TECNICO', 'Técnico'),
        ('DOCTOR', 'Doctor'),
        ('VENDEDOR', 'Vendedor'),
        ('OTRO', 'Otro'),
    ]
    pedido = models.ForeignKey(Pedido, related_name='comisiones', on_delete=models.CASCADE)
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default='TECNICO')
    beneficiario = models.CharField(max_length=255)
    monto = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    notas = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        verbose_name = "Comisión de pedido"
        verbose_name_plural = "Comisiones de pedido"

    def __str__(self):
        return f"{self.get_tipo_display()} {self.beneficiario}: {self.monto}"


class Cotizacion(models.Model):
    """Cotización previa al pedido. Al aceptarse se convierte en un Pedido."""
    ESTADO_CHOICES = [
        ('BORRADOR', 'Borrador'),
        ('ENVIADA', 'Enviada'),
        ('ACEPTADA', 'Aceptada'),
        ('RECHAZADA', 'Rechazada'),
        ('CONVERTIDA', 'Convertida en pedido'),
        ('VENCIDA', 'Vencida'),
    ]

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    sucursal = models.ForeignKey(Sucursal, on_delete=models.CASCADE, related_name='cotizaciones')
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='cotizaciones')
    moneda = models.ForeignKey(Moneda, on_delete=models.PROTECT)

    folio = models.CharField(max_length=25, unique=True)
    consecutivo = models.IntegerField(default=0)
    fecha_emision = models.DateField(auto_now_add=True)
    vigencia = models.DateField(null=True, blank=True, help_text="Válida hasta")

    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default='BORRADOR')
    notas = models.TextField(blank=True)

    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    impuestos = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='cotizaciones_creadas')
    pedido_generado = models.ForeignKey(
        Pedido, on_delete=models.SET_NULL, null=True, blank=True, related_name='cotizacion_origen')

    class Meta:
        ordering = ['-fecha_emision', '-id']
        verbose_name = "Cotización"
        verbose_name_plural = "Cotizaciones"

    def color_estado(self):
        return {
            'BORRADOR': 'amber', 'ENVIADA': 'blue', 'ACEPTADA': 'indigo',
            'RECHAZADA': 'rose', 'CONVERTIDA': 'emerald', 'VENCIDA': 'slate',
        }.get(self.estado, 'slate')

    def __str__(self):
        return f"{self.folio} - {self.cliente}"


class DetalleCotizacion(models.Model):
    cotizacion = models.ForeignKey(Cotizacion, related_name='detalles', on_delete=models.CASCADE)
    producto = models.ForeignKey('admon_inventarios.Producto', on_delete=models.PROTECT)
    tipo_linea = models.CharField(max_length=10, choices=DetallePedido.LINEA_CHOICES,
                                  default=DetallePedido.LINEA_PRODUCTO)
    cantidad = models.DecimalField(max_digits=12, decimal_places=4)
    precio_unitario = models.DecimalField(max_digits=14, decimal_places=4)
    impuesto = models.ForeignKey(
        'admon_empresas.Impuesto', on_delete=models.SET_NULL, null=True, blank=True)
    iva_porcentaje = models.DecimalField(max_digits=7, decimal_places=4, default=16)
    es_retencion = models.BooleanField(default=False)

    @property
    def importe(self):
        return self.cantidad * self.precio_unitario

    def __str__(self):
        return f"{self.producto.sku} x{self.cantidad}"
