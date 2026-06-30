import decimal

from django.db import models
from django.conf import settings

from admon_empresas.models import Empresa, Moneda, Sucursal


class MetodoPago(models.Model):
    """Catálogo de formas de pago por empresa (efectivo, transferencia, etc.)."""
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='metodos_pago')
    nombre = models.CharField(max_length=50)
    clave_sat = models.CharField(max_length=10, blank=True, null=True, help_text="Clave SAT forma de pago (futuro CFDI)")
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Método de pago"
        verbose_name_plural = "Métodos de pago"
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class FacturaProveedor(models.Model):
    """Factura que el proveedor nos emite contra una orden de compra.
    Una OC puede tener varias (facturación parcial). Genera saldo por pagar."""
    ESTADO_CHOICES = [
        ('PENDIENTE', 'Pendiente de pago'),
        ('PARCIAL', 'Pago parcial'),
        ('PAGADA', 'Pagada'),
        ('CANCELADA', 'Cancelada'),
    ]

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='facturas_proveedor')
    orden_compra = models.ForeignKey(
        'admon_compras.OrdenCompra', on_delete=models.PROTECT, related_name='facturas')
    proveedor = models.ForeignKey('admon_compras.Proveedor', on_delete=models.PROTECT)

    folio = models.CharField(max_length=50, help_text="Folio de la factura del proveedor")
    uuid_cfdi = models.CharField(max_length=40, blank=True, null=True, help_text="UUID del CFDI (opcional)")
    fecha_emision = models.DateField()
    fecha_vencimiento = models.DateField(null=True, blank=True)

    moneda = models.ForeignKey(Moneda, on_delete=models.PROTECT)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    impuestos = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2)

    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default='PENDIENTE')
    notas = models.TextField(blank=True, null=True)

    # CFDI del proveedor
    archivo_xml = models.FileField(upload_to='cfdi/facturas/xml/', null=True, blank=True)
    archivo_pdf = models.FileField(upload_to='cfdi/facturas/pdf/', null=True, blank=True)

    registrada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_emision', '-id']
        verbose_name = "Factura de proveedor"
        verbose_name_plural = "Facturas de proveedor"

    @property
    def total_pagado(self):
        """Suma de lo aplicado a esta factura, en su propia moneda."""
        agg = self.aplicaciones.aggregate(s=models.Sum('monto_aplicado'))
        return agg['s'] or decimal.Decimal('0')

    @property
    def saldo(self):
        return self.total - self.total_pagado

    def recalcular_estado(self):
        if self.estado == 'CANCELADA':
            return
        pagado = self.total_pagado
        if pagado <= 0:
            self.estado = 'PENDIENTE'
        elif pagado < self.total:
            self.estado = 'PARCIAL'
        else:
            self.estado = 'PAGADA'
        self.save(update_fields=['estado'])

    def color_estado(self):
        return {'PENDIENTE': 'amber', 'PARCIAL': 'blue', 'PAGADA': 'emerald', 'CANCELADA': 'slate'}.get(self.estado, 'slate')

    def __str__(self):
        return f"Factura {self.folio} — {self.proveedor}"


class FacturaCliente(models.Model):
    """Factura/cuenta por cobrar que la empresa emite a un cliente contra
    un pedido de venta. Un pedido puede tener varias (entregas parciales)."""
    ESTADO_CHOICES = [
        ('PENDIENTE', 'Pendiente de cobro'),
        ('PARCIAL', 'Cobro parcial'),
        ('PAGADA', 'Cobrada'),
        ('CANCELADA', 'Cancelada'),
    ]

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='facturas_cliente')
    pedido = models.ForeignKey(
        'admon_ventas.Pedido', on_delete=models.PROTECT, related_name='facturas')
    cliente = models.ForeignKey('admon_ventas.Cliente', on_delete=models.PROTECT)

    folio = models.CharField(max_length=25, help_text="Folio interno de la cuenta por cobrar")
    uuid_cfdi = models.CharField(max_length=40, blank=True, null=True, help_text="UUID del CFDI emitido (opcional)")
    fecha_emision = models.DateField()
    fecha_vencimiento = models.DateField(null=True, blank=True)

    moneda = models.ForeignKey(Moneda, on_delete=models.PROTECT)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    impuestos = models.DecimalField(max_digits=14, decimal_places=2, default=0,
                                    help_text="IVA trasladado (suma al total)")
    retenciones = models.DecimalField(max_digits=14, decimal_places=2, default=0,
                                      help_text="ISR/IVA retenidos (restan del total). Servicios.")
    total = models.DecimalField(max_digits=14, decimal_places=2)

    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default='PENDIENTE')
    notas = models.TextField(blank=True, null=True)

    # CFDI emitido al cliente
    archivo_xml = models.FileField(upload_to='cfdi/cobrar/xml/', null=True, blank=True)
    archivo_pdf = models.FileField(upload_to='cfdi/cobrar/pdf/', null=True, blank=True)

    registrada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_emision', '-id']
        verbose_name = "Factura de cliente"
        verbose_name_plural = "Facturas de cliente"

    @property
    def total_pagado(self):
        agg = self.aplicaciones.aggregate(s=models.Sum('monto_aplicado'))
        return agg['s'] or decimal.Decimal('0')

    @property
    def saldo(self):
        return self.total - self.total_pagado

    def recalcular_estado(self):
        if self.estado == 'CANCELADA':
            return
        pagado = self.total_pagado
        if pagado <= 0:
            self.estado = 'PENDIENTE'
        elif pagado < self.total:
            self.estado = 'PARCIAL'
        else:
            self.estado = 'PAGADA'
        self.save(update_fields=['estado'])

    def color_estado(self):
        return {'PENDIENTE': 'amber', 'PARCIAL': 'blue', 'PAGADA': 'emerald', 'CANCELADA': 'slate'}.get(self.estado, 'slate')

    @property
    def total_facturado(self):
        """Suma de los CFDI ligados a esta CxC (el contador puede subir varios
        hasta cubrir el total). Compat: si no hay CFDI hijos pero sí un UUID/XML
        único antiguo, se considera facturado el total."""
        try:
            s = sum((c.total for c in self.cfdis.all()), decimal.Decimal('0'))
        except Exception:
            s = self.cfdis.aggregate(x=models.Sum('total'))['x'] or decimal.Decimal('0')
        if s <= 0 and (bool(self.uuid_cfdi) or bool(self.archivo_xml)):
            return self.total
        return s

    @property
    def saldo_por_facturar(self):
        r = self.total - self.total_facturado
        return r if r > 0 else decimal.Decimal('0')

    @property
    def esta_facturada(self):
        """True solo cuando lo facturado cubre el total de la CxC (con tolerancia)."""
        return self.total_facturado >= (self.total - decimal.Decimal('0.01'))

    @property
    def estado_facturacion(self):
        tf = self.total_facturado
        if tf <= 0:
            return 'PENDIENTE_FACTURAR'
        if tf < self.total - decimal.Decimal('0.01'):
            return 'PARCIAL_FACTURAR'
        return 'FACTURADA'

    def estado_facturacion_display(self):
        return {
            'PENDIENTE_FACTURAR': 'Pendiente de facturar',
            'PARCIAL_FACTURAR': 'Facturación parcial',
            'FACTURADA': 'Facturado',
        }[self.estado_facturacion]

    def color_facturacion(self):
        return {'PENDIENTE_FACTURAR': 'amber', 'PARCIAL_FACTURAR': 'blue',
                'FACTURADA': 'emerald'}[self.estado_facturacion]

    def __str__(self):
        return f"CxC {self.folio} — {self.cliente}"


class CfdiCliente(models.Model):
    """CFDI emitido ligado a una Cuenta por Cobrar. Una CxC puede tener varios
    (facturación por artículo o parcial), por eso es una tabla aparte."""
    factura = models.ForeignKey(
        FacturaCliente, on_delete=models.CASCADE, related_name='cfdis')
    uuid = models.CharField(max_length=40)
    serie_folio = models.CharField(max_length=60, blank=True, default='')
    fecha = models.DateField(null=True, blank=True)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    archivo_xml = models.FileField(upload_to='cfdi/cobrar/xml/', null=True, blank=True)
    archivo_pdf = models.FileField(upload_to='cfdi/cobrar/pdf/', null=True, blank=True)
    cargado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('factura', 'uuid')
        ordering = ['fecha', 'id']
        verbose_name = "CFDI de cliente"
        verbose_name_plural = "CFDI de cliente"

    def __str__(self):
        return f"{self.uuid} — {self.factura.folio}"


class Pago(models.Model):
    """Egreso (a proveedor) o ingreso (de cliente, futuro). Puede aplicarse
    a una o varias facturas. Soporta moneda distinta con tipo de cambio."""
    TIPO_EGRESO = 'EGRESO'
    TIPO_INGRESO = 'INGRESO'
    TIPO_CHOICES = [
        (TIPO_EGRESO, 'Egreso (pago a proveedor)'),
        (TIPO_INGRESO, 'Ingreso (cobro a cliente)'),
    ]

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='pagos')
    tipo = models.CharField(max_length=8, choices=TIPO_CHOICES, default=TIPO_EGRESO)
    folio = models.CharField(max_length=20, blank=True)

    proveedor = models.ForeignKey('admon_compras.Proveedor', on_delete=models.PROTECT, null=True, blank=True)
    cliente = models.ForeignKey('admon_ventas.Cliente', on_delete=models.PROTECT, null=True, blank=True)

    fecha = models.DateField()
    moneda = models.ForeignKey(Moneda, on_delete=models.PROTECT)
    monto = models.DecimalField(max_digits=14, decimal_places=2, default=0,
                                help_text="Total del pago en su propia moneda (suma de aplicaciones)")
    metodo = models.ForeignKey(MetodoPago, on_delete=models.PROTECT, null=True, blank=True)
    cuenta_banco = models.CharField(max_length=100, blank=True, null=True, help_text="Cuenta/banco de donde salió (informativo)")
    referencia = models.CharField(max_length=100, blank=True, null=True)
    notas = models.TextField(blank=True, null=True)

    # Complemento de pago (REP) que emite el proveedor; suele llegar después
    uuid_complemento = models.CharField(max_length=40, blank=True, null=True)
    fecha_complemento = models.DateField(null=True, blank=True)
    complemento_xml = models.FileField(upload_to='cfdi/complementos/xml/', null=True, blank=True)
    complemento_pdf = models.FileField(upload_to='cfdi/complementos/pdf/', null=True, blank=True)

    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    creado_en = models.DateTimeField(auto_now_add=True)

    @property
    def tiene_complemento(self):
        return bool(self.complemento_xml or self.uuid_complemento)

    class Meta:
        ordering = ['-fecha', '-id']
        verbose_name = "Pago"
        verbose_name_plural = "Pagos"

    def save(self, *args, **kwargs):
        if not self.folio:
            prefijo = 'EGR' if self.tipo == self.TIPO_EGRESO else 'ING'
            ultimo = Pago.objects.filter(empresa=self.empresa, tipo=self.tipo).count() + 1
            self.folio = f"{prefijo}-{ultimo:05d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.folio} — {self.moneda.simbolo}{self.monto}"


class AplicacionPago(models.Model):
    """Cuánto de un pago se aplica a una factura específica.
    monto_aplicado está en la moneda de la FACTURA; tipo_cambio convierte
    a la moneda del pago (cuántas unidades de moneda_pago por 1 de moneda_factura)."""
    pago = models.ForeignKey(Pago, on_delete=models.CASCADE, related_name='aplicaciones')
    # Una aplicación apunta a una factura de proveedor (egreso) O de cliente (ingreso)
    factura = models.ForeignKey(FacturaProveedor, on_delete=models.PROTECT,
                                null=True, blank=True, related_name='aplicaciones')
    factura_cliente = models.ForeignKey(FacturaCliente, on_delete=models.PROTECT,
                                        null=True, blank=True, related_name='aplicaciones')
    monto_aplicado = models.DecimalField(max_digits=14, decimal_places=2,
                                         help_text="En la moneda de la factura")
    tipo_cambio = models.DecimalField(max_digits=12, decimal_places=6, default=1,
                                      help_text="Moneda_pago por 1 de moneda_factura (1 si misma moneda)")

    @property
    def documento(self):
        """La factura a la que aplica, sea de proveedor o de cliente."""
        return self.factura or self.factura_cliente

    @property
    def monto_en_pago(self):
        return self.monto_aplicado * self.tipo_cambio

    def __str__(self):
        doc = self.documento
        return f"{self.pago.folio} → {doc.folio if doc else '?'}: {self.monto_aplicado}"


class CategoriaGasto(models.Model):
    """Categoría para clasificar gastos de operación (renta, sueldos, etc.)."""
    CLASIF_CHOICES = [
        ('VENTA', 'Gastos de venta'),
        ('ADMIN', 'Gastos de administración'),
        ('FINANCIERO', 'Gastos financieros'),
        ('OTRO', 'Otros gastos'),
    ]
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='categorias_gasto')
    nombre = models.CharField(max_length=80)
    clasificacion = models.CharField(max_length=12, choices=CLASIF_CHOICES, default='ADMIN')
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Categoría de gasto"
        verbose_name_plural = "Categorías de gasto"
        ordering = ['clasificacion', 'nombre']
        unique_together = ('empresa', 'nombre')

    def __str__(self):
        return self.nombre


class Gasto(models.Model):
    """Gasto de operación (no inventario): renta, servicios, sueldos, comisiones,
    envíos, financieros, etc. Importes sin IVA para el estado de resultados."""
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='gastos')
    sucursal = models.ForeignKey(Sucursal, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='gastos')
    categoria = models.ForeignKey(CategoriaGasto, on_delete=models.PROTECT, related_name='gastos')

    fecha = models.DateField()
    descripcion = models.CharField(max_length=255)
    proveedor_nombre = models.CharField(max_length=160, blank=True, help_text="A quién se le pagó")

    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0,
                                   help_text="Importe sin IVA")
    iva = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    metodo = models.ForeignKey(MetodoPago, on_delete=models.SET_NULL, null=True, blank=True)
    referencia = models.CharField(max_length=80, blank=True)
    comprobante = models.FileField(upload_to='gastos/', null=True, blank=True)
    uuid_cfdi = models.CharField(max_length=40, blank=True, null=True)

    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   related_name='gastos_registrados')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Gasto"
        verbose_name_plural = "Gastos"
        ordering = ['-fecha', '-id']

    def __str__(self):
        return f"{self.fecha} · {self.descripcion} · ${self.total}"


class PartidaResultado(models.Model):
    """Partidas no operativas e impuestos del estado de resultados:
    otros ingresos, otros gastos (no operativos) e impuestos (ISR, etc.)."""
    NATURALEZA_CHOICES = [
        ('OTRO_INGRESO', 'Otros ingresos'),
        ('OTRO_EGRESO', 'Otros gastos (no operativos)'),
        ('IMPUESTO', 'Impuestos'),
    ]
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='partidas_resultado')
    naturaleza = models.CharField(max_length=14, choices=NATURALEZA_CHOICES)
    fecha = models.DateField()
    concepto = models.CharField(max_length=200)
    monto = models.DecimalField(max_digits=14, decimal_places=2, default=0,
                                help_text="Importe positivo; el signo lo da la naturaleza")
    referencia = models.CharField(max_length=80, blank=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   related_name='partidas_resultado')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Partida de resultado"
        verbose_name_plural = "Partidas de resultado"
        ordering = ['-fecha', '-id']

    def __str__(self):
        return f"{self.get_naturaleza_display()} · {self.concepto} · ${self.monto}"


class ComprobanteSAT(models.Model):
    """CFDI descargado del SAT (emitido o recibido) para conciliar contra el
    sistema. Se sube el XML manualmente; se guarda su metadata por UUID."""
    DIRECCION_CHOICES = [('EMITIDO', 'Emitido (venta)'), ('RECIBIDO', 'Recibido (compra/gasto)')]

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='comprobantes_sat')
    uuid = models.CharField(max_length=40)
    direccion = models.CharField(max_length=8, choices=DIRECCION_CHOICES)
    tipo = models.CharField(max_length=2, blank=True, help_text="I/E/P/N (ingreso, egreso, pago, nómina)")
    fecha = models.DateField(null=True, blank=True)

    rfc_emisor = models.CharField(max_length=15, blank=True)
    nombre_emisor = models.CharField(max_length=200, blank=True)
    rfc_receptor = models.CharField(max_length=15, blank=True)
    nombre_receptor = models.CharField(max_length=200, blank=True)

    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    iva = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    serie_folio = models.CharField(max_length=60, blank=True)

    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Comprobante SAT"
        verbose_name_plural = "Comprobantes SAT"
        ordering = ['-fecha', '-id']
        unique_together = ('empresa', 'uuid')

    def __str__(self):
        return f"{self.uuid} · {self.get_direccion_display()} · ${self.total}"
