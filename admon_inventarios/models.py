from django.db import models
from django.contrib.auth.models import User
from admon_empresas.models import Empresa, Sucursal


# Propiedad del stock: propio de la empresa o a consignación de un tercero.
PROPIEDAD_PROPIO = 'PROPIO'
PROPIEDAD_CONSIGNA = 'CONSIGNA'
PROPIEDAD_CHOICES = [
    (PROPIEDAD_PROPIO, 'Propio'),
    (PROPIEDAD_CONSIGNA, 'Consignación'),
]


class Consignante(models.Model):
    """Tercero dueño de mercancía que la empresa tiene a consignación
    (ej. el fabricante de prótesis cuyas piezas resguarda Insermed)."""
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='consignantes')
    nombre = models.CharField(max_length=255)
    rfc = models.CharField(max_length=15, blank=True, null=True)
    contacto = models.CharField(max_length=120, blank=True, null=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Consignante"
        verbose_name_plural = "Consignantes"
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


# =========================================================
# 1. CATÁLOGOS DE CLASIFICACIÓN (por Empresa)
# =========================================================

class Clase(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    codigo = models.CharField(max_length=10)
    descripcion = models.CharField(max_length=100)

    class Meta:
        unique_together = ('empresa', 'codigo')

    def __str__(self):
        return f"{self.codigo} - {self.descripcion}"


class Grupo(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    codigo = models.CharField(max_length=10)
    descripcion = models.CharField(max_length=100)
    es_inventariable = models.BooleanField(default=True, help_text="¿Este grupo genera movimientos de stock?")
    ubicacion_defecto = models.ForeignKey(
        'Ubicacion', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='grupos_predeterminados'
    )

    class Meta:
        unique_together = ('empresa', 'codigo')

    def __str__(self):
        return f"{self.codigo} - {self.descripcion}"


class Tipo(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    codigo = models.CharField(max_length=10)
    descripcion = models.CharField(max_length=100)

    class Meta:
        unique_together = ('empresa', 'codigo')

    def __str__(self):
        return f"{self.codigo} - {self.descripcion}"


class UnidadMedida(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    codigo = models.CharField(max_length=10)       # KG, PZA, LT, SER
    descripcion = models.CharField(max_length=100)

    class Meta:
        unique_together = ('empresa', 'codigo')

    def __str__(self):
        return f"{self.codigo} - {self.descripcion}"


# =========================================================
# 2. ESTRUCTURA FÍSICA: ALMACENES Y UBICACIONES (por Sucursal)
# =========================================================

class Almacen(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    sucursal = models.ForeignKey(Sucursal, on_delete=models.CASCADE, related_name='almacenes')
    codigo = models.CharField(max_length=10)
    nombre = models.CharField(max_length=100)
    direccion = models.TextField(blank=True, null=True)
    activo = models.BooleanField(default=True)

    class Meta:
        unique_together = ('sucursal', 'codigo')
        verbose_name_plural = "Almacenes"

    def __str__(self):
        return f"{self.nombre} ({self.sucursal.nombre})"


class Ubicacion(models.Model):
    almacen = models.ForeignKey(Almacen, on_delete=models.CASCADE, related_name='ubicaciones')
    codigo = models.CharField(max_length=20)
    descripcion = models.CharField(max_length=100)
    activa = models.BooleanField(default=True)

    class Meta:
        unique_together = ('almacen', 'codigo')
        verbose_name_plural = "Ubicaciones"

    def __str__(self):
        return f"{self.almacen.nombre} > {self.codigo}"


# =========================================================
# 3. PRODUCTOS
# =========================================================

class Producto(models.Model):
    ALCANCE_GLOBAL = 'GLOBAL'
    ALCANCE_SUCURSAL = 'SUCURSAL'
    ALCANCE_CHOICES = [
        (ALCANCE_GLOBAL, 'Global (todas las sucursales)'),
        (ALCANCE_SUCURSAL, 'Por sucursal (solo asignadas)'),
    ]

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='productos')

    # Clasificación
    clase = models.ForeignKey(Clase, on_delete=models.PROTECT, null=True, blank=True)
    grupo = models.ForeignKey(Grupo, on_delete=models.PROTECT, null=True, blank=True)
    tipo = models.ForeignKey(Tipo, on_delete=models.PROTECT, null=True, blank=True)
    unidad_medida = models.ForeignKey(UnidadMedida, on_delete=models.PROTECT, null=True, blank=True)

    # Datos base
    sku = models.CharField(max_length=50, help_text="Código interno")
    nombre = models.CharField(max_length=255)
    descripcion = models.TextField(blank=True, null=True)
    codigo_barras = models.CharField(max_length=50, blank=True, null=True, help_text="EAN/UPC")
    imagen = models.ImageField(upload_to='productos/', null=True, blank=True)

    # Alcance: global por empresa o restringido a sucursales asignadas
    alcance = models.CharField(max_length=10, choices=ALCANCE_CHOICES, default=ALCANCE_GLOBAL)

    # Trazabilidad: definen qué se pide en entradas/salidas
    es_loteable = models.BooleanField(default=False, help_text="¿Maneja número de lote y caducidad?")
    es_serializable = models.BooleanField(default=False, help_text="¿Maneja números de serie únicos?")

    # Naturaleza del producto (configurable por tipo de empresa)
    es_comprable = models.BooleanField(default=True, help_text="¿Se puede comprar a proveedores?")
    es_vendible = models.BooleanField(default=True, help_text="¿Se puede vender a clientes?")
    es_materia_prima = models.BooleanField(default=False, help_text="¿Es insumo para producción?")
    es_producible = models.BooleanField(default=False, help_text="¿Se fabrica mediante una receta/BOM?")
    es_retornable = models.BooleanField(default=False, help_text="¿Es herramienta/préstamo que regresa? (kits)")

    # Impuesto por defecto del producto (opcional; si falta, se usa el default de la empresa)
    impuesto = models.ForeignKey(
        'admon_empresas.Impuesto', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='productos')

    # Datos regulatorios (opcional — ej. prótesis médicas)
    registro_sanitario = models.CharField(max_length=100, blank=True, null=True)

    # Costos y precios base (pueden tener override por sucursal)
    costo_unitario = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    precio_venta = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    # Tarifa de renta para productos retornables (instrumental que se presta y se cobra como renta)
    precio_renta = models.DecimalField(max_digits=18, decimal_places=4, default=0,
                                       help_text="Tarifa de renta si el producto es retornable/préstamo")

    ubicacion_defecto = models.ForeignKey(
        Ubicacion, on_delete=models.SET_NULL, null=True, blank=True,
        help_text="Opcional. Si se deja vacío, usará la del Grupo."
    )

    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('empresa', 'sku')

    def __str__(self):
        return f"[{self.sku}] {self.nombre}"


class ProductoSucursal(models.Model):
    """Configuración de un producto en una sucursal específica.
    Si el producto es de alcance SUCURSAL, sólo existe donde tenga registro aquí.
    Si es GLOBAL, este registro es opcional y sólo aplica overrides."""
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name='config_sucursales')
    sucursal = models.ForeignKey(Sucursal, on_delete=models.CASCADE, related_name='productos_config')

    activo_en_sucursal = models.BooleanField(default=True)
    precio_venta_override = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    costo_unitario_override = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)

    stock_minimo = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    stock_maximo = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    punto_reorden = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)

    class Meta:
        unique_together = ('producto', 'sucursal')
        verbose_name_plural = "Productos por sucursal"

    def __str__(self):
        return f"{self.producto.sku} @ {self.sucursal.nombre}"


# =========================================================
# 4. TRAZABILIDAD: LOTES Y NÚMEROS DE SERIE
# =========================================================

class Lote(models.Model):
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name='lotes')
    numero_lote = models.CharField(max_length=100)
    fecha_fabricacion = models.DateField(null=True, blank=True)
    fecha_caducidad = models.DateField(null=True, blank=True)

    class Meta:
        unique_together = ('producto', 'numero_lote')

    def __str__(self):
        return f"Lote {self.numero_lote} | Exp: {self.fecha_caducidad or 'N/A'}"


class NumeroSerie(models.Model):
    ESTADO_CHOICES = [
        ('DISPONIBLE', 'Disponible'),
        ('EN_KIT', 'Asignada a kit en campo'),
        ('VENDIDA', 'Vendida / consumida'),
        ('EN_TRANSITO', 'En tránsito (traspaso)'),
        ('BAJA', 'Dada de baja'),
    ]
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name='series')
    serie = models.CharField(max_length=100)
    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES, default='DISPONIBLE')

    class Meta:
        unique_together = ('producto', 'serie')

    def __str__(self):
        return f"S/N: {self.serie} ({self.estado})"


# =========================================================
# 5. EXISTENCIAS Y MOVIMIENTOS (núcleo del inventario)
# =========================================================

class Existencia(models.Model):
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE)
    sucursal = models.ForeignKey(Sucursal, on_delete=models.CASCADE)
    almacen = models.ForeignKey(Almacen, on_delete=models.CASCADE)
    ubicacion = models.ForeignKey(Ubicacion, on_delete=models.CASCADE)

    lote = models.ForeignKey(Lote, on_delete=models.CASCADE, null=True, blank=True)
    serie = models.ForeignKey(NumeroSerie, on_delete=models.CASCADE, null=True, blank=True)

    # Propiedad: stock propio vs. a consignación de un tercero (se mantiene separado)
    propiedad = models.CharField(max_length=10, choices=PROPIEDAD_CHOICES, default=PROPIEDAD_PROPIO)
    consignante = models.ForeignKey(Consignante, on_delete=models.PROTECT, null=True, blank=True)

    cantidad = models.DecimalField(max_digits=12, decimal_places=4, default=0)

    class Meta:
        unique_together = ('producto', 'ubicacion', 'lote', 'serie', 'propiedad', 'consignante')

    def __str__(self):
        return f"{self.producto.sku} @ {self.ubicacion}: {self.cantidad}"


class MovimientoInventario(models.Model):
    """Kardex unificado: todo cambio de stock pasa por aquí,
    sin importar el módulo que lo origine."""
    TIPO_CHOICES = [
        ('ENTRADA', 'Entrada'),
        ('SALIDA', 'Salida'),
        ('AJUSTE_POS', 'Ajuste positivo'),
        ('AJUSTE_NEG', 'Ajuste negativo'),
        ('TRASPASO_SAL', 'Traspaso - salida'),
        ('TRASPASO_ENT', 'Traspaso - entrada'),
        ('KIT_SALIDA', 'Kit - salida a campo'),
        ('KIT_RETORNO', 'Kit - retorno de campo'),
        ('KIT_CONSUMO', 'Kit - consumido en cirugía'),
        ('CAJA_REAB_SAL', 'Caja - salida de almacén (reabasto)'),
        ('CAJA_REAB_ENT', 'Caja - entrada a caja (reabasto)'),
        ('PROD_CONSUMO', 'Producción - consumo de insumo'),
        ('PROD_ENTRADA', 'Producción - entrada de terminado'),
        ('VENTA', 'Venta / consumo'),
    ]
    ORIGEN_CHOICES = [
        ('RECEPCION', 'Recepción de material'),
        ('OC', 'Orden de compra'),
        ('TRASPASO', 'Traspaso entre sucursales'),
        ('PRODUCCION', 'Orden de producción'),
        ('KIT', 'Salida de kit'),
        ('AJUSTE', 'Ajuste manual'),
        ('VENTA', 'Venta'),
    ]

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    sucursal = models.ForeignKey(Sucursal, on_delete=models.CASCADE)
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name='movimientos')
    almacen = models.ForeignKey(Almacen, on_delete=models.PROTECT)
    ubicacion = models.ForeignKey(Ubicacion, on_delete=models.PROTECT)

    lote = models.ForeignKey(Lote, on_delete=models.PROTECT, null=True, blank=True)
    serie = models.ForeignKey(NumeroSerie, on_delete=models.PROTECT, null=True, blank=True)

    propiedad = models.CharField(max_length=10, choices=PROPIEDAD_CHOICES, default=PROPIEDAD_PROPIO)
    consignante = models.ForeignKey(Consignante, on_delete=models.PROTECT, null=True, blank=True)

    tipo = models.CharField(max_length=15, choices=TIPO_CHOICES)
    origen = models.CharField(max_length=15, choices=ORIGEN_CHOICES)
    # Referencia al documento que lo originó (folio de traspaso, recepción, etc.)
    referencia = models.CharField(max_length=50, blank=True, null=True)

    cantidad = models.DecimalField(max_digits=12, decimal_places=4)
    costo_unitario = models.DecimalField(max_digits=18, decimal_places=4, default=0)

    fecha = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(User, on_delete=models.PROTECT)
    notas = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-fecha']
        verbose_name_plural = "Movimientos de inventario"

    def __str__(self):
        return f"{self.tipo} {self.producto.sku} x{self.cantidad}"


# =========================================================
# 6. RECEPCIONES (directas o desde OC futura)
# =========================================================

class RecepcionMaterial(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    sucursal = models.ForeignKey(Sucursal, on_delete=models.CASCADE)
    folio = models.CharField(max_length=20, blank=True)

    # Si viene de una orden de compra se liga aquí; si no, es recepción directa
    orden_compra = models.ForeignKey(
        'admon_compras.OrdenCompra', on_delete=models.PROTECT,
        null=True, blank=True, related_name='recepciones')
    proveedor_nombre = models.CharField(max_length=255, blank=True, null=True,
                                        help_text="Para recepciones directas sin OC")
    remision_proveedor = models.CharField(max_length=50, blank=True, null=True)
    numero_factura = models.CharField(max_length=50, blank=True, null=True)

    fecha_recepcion = models.DateTimeField(auto_now_add=True)
    recibido_por = models.ForeignKey(User, on_delete=models.PROTECT)
    notas = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-fecha_recepcion']
        verbose_name_plural = "Recepciones de material"

    def save(self, *args, **kwargs):
        if not self.folio:
            ultimo = RecepcionMaterial.objects.filter(empresa=self.empresa).count() + 1
            self.folio = f"REC-{ultimo:05d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.folio}"


class DetalleRecepcion(models.Model):
    recepcion = models.ForeignKey(RecepcionMaterial, related_name='detalles', on_delete=models.CASCADE)
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    # Partida de la OC que se está recibiendo (null en recepción directa)
    detalle_oc = models.ForeignKey(
        'admon_compras.DetalleOrdenCompra', on_delete=models.PROTECT,
        null=True, blank=True, related_name='recepciones')
    cantidad_recibida = models.DecimalField(max_digits=12, decimal_places=4)
    ubicacion = models.ForeignKey(Ubicacion, on_delete=models.PROTECT)
    lote = models.ForeignKey(Lote, on_delete=models.PROTECT, null=True, blank=True)
    costo_unitario = models.DecimalField(max_digits=18, decimal_places=4, default=0)

    def __str__(self):
        return f"{self.producto.sku} x{self.cantidad_recibida}"


class SerieRecepcion(models.Model):
    """Series individuales que entraron en una partida de recepción."""
    detalle = models.ForeignKey(DetalleRecepcion, related_name='series_recibidas', on_delete=models.CASCADE)
    serie = models.ForeignKey(NumeroSerie, on_delete=models.PROTECT)


# =========================================================
# 7. TRASPASOS ENTRE SUCURSALES
# =========================================================

class SolicitudTraspaso(models.Model):
    ESTADO_CHOICES = [
        ('SOLICITADO', 'Solicitado'),
        ('APROBADO', 'Aprobado'),
        ('RECHAZADO', 'Rechazado'),
        ('EN_TRANSITO', 'En tránsito'),
        ('RECIBIDO', 'Recibido'),
        ('RECIBIDO_PARCIAL', 'Recibido parcial'),
        ('CANCELADO', 'Cancelado'),
    ]

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    folio = models.CharField(max_length=20, blank=True)

    sucursal_origen = models.ForeignKey(Sucursal, on_delete=models.PROTECT, related_name='traspasos_salientes')
    sucursal_destino = models.ForeignKey(Sucursal, on_delete=models.PROTECT, related_name='traspasos_entrantes')

    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='SOLICITADO')

    # Trazabilidad del flujo: quién y cuándo en cada paso
    solicitado_por = models.ForeignKey(User, on_delete=models.PROTECT, related_name='traspasos_solicitados')
    fecha_solicitud = models.DateTimeField(auto_now_add=True)

    aprobado_por = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name='traspasos_aprobados')
    fecha_aprobacion = models.DateTimeField(null=True, blank=True)

    enviado_por = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name='traspasos_enviados')
    fecha_envio = models.DateTimeField(null=True, blank=True)

    recibido_por = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name='traspasos_recibidos')
    fecha_recepcion = models.DateTimeField(null=True, blank=True)

    notas_solicitud = models.TextField(blank=True, null=True)
    notas_envio = models.TextField(blank=True, null=True)
    notas_recepcion = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-fecha_solicitud']
        verbose_name_plural = "Solicitudes de traspaso"

    def save(self, *args, **kwargs):
        if not self.folio:
            ultimo = SolicitudTraspaso.objects.filter(empresa=self.empresa).count() + 1
            self.folio = f"TRA-{ultimo:05d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.folio}: {self.sucursal_origen.nombre} → {self.sucursal_destino.nombre} [{self.estado}]"


class DetalleTraspaso(models.Model):
    solicitud = models.ForeignKey(SolicitudTraspaso, related_name='detalles', on_delete=models.CASCADE)
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    cantidad_solicitada = models.DecimalField(max_digits=12, decimal_places=4)
    cantidad_enviada = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    cantidad_recibida = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    # Ubicación destino donde se acomoda al recibir
    ubicacion_destino = models.ForeignKey(Ubicacion, on_delete=models.PROTECT, null=True, blank=True,
                                          related_name='traspasos_recibidos')

    def __str__(self):
        return f"{self.producto.sku} sol:{self.cantidad_solicitada}"


class TrazabilidadTraspaso(models.Model):
    """Qué lotes/series específicos viajaron en cada partida del traspaso."""
    detalle = models.ForeignKey(DetalleTraspaso, related_name='trazabilidad', on_delete=models.CASCADE)
    lote = models.ForeignKey(Lote, on_delete=models.PROTECT, null=True, blank=True)
    serie = models.ForeignKey(NumeroSerie, on_delete=models.PROTECT, null=True, blank=True)
    cantidad = models.DecimalField(max_digits=12, decimal_places=4)
    # Ubicación de origen de donde se tomó el material
    ubicacion_origen = models.ForeignKey(Ubicacion, on_delete=models.PROTECT, null=True, blank=True)


# =========================================================
# 8. KITS / CAJAS QUIRÚRGICAS (ej. Insermed)
#    (Producción se movió a la app admon_produccion)
# =========================================================

class Kit(models.Model):
    """Plantilla: define qué debe contener una caja de este tipo."""
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    codigo = models.CharField(max_length=20)
    nombre = models.CharField(max_length=255)
    descripcion = models.TextField(blank=True, null=True)
    activo = models.BooleanField(default=True)

    class Meta:
        unique_together = ('empresa', 'codigo')

    def __str__(self):
        return f"[{self.codigo}] {self.nombre}"


class DetalleKit(models.Model):
    """Composición estándar del kit (lo que se debe rellenar)."""
    kit = models.ForeignKey(Kit, related_name='componentes', on_delete=models.CASCADE)
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    cantidad_requerida = models.DecimalField(max_digits=12, decimal_places=4)
    es_retornable = models.BooleanField(
        default=False,
        help_text="True = herramienta/préstamo que siempre regresa. False = consumible que puede usarse."
    )
    notas = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"{self.producto.sku} x{self.cantidad_requerida}"


class InstanciaKit(models.Model):
    """Caja física identificable. Puede salir y regresar N veces."""
    ESTADO_CHOICES = [
        ('DISPONIBLE', 'Disponible'),
        ('EN_PREPARACION', 'En preparación'),
        ('EN_CAMPO', 'En campo (hospital)'),
        ('RETORNADA', 'Retornada (pendiente revisión)'),
        ('REABASTECIENDO', 'Reabasteciendo'),
        ('BAJA', 'Dada de baja'),
    ]
    # La caja puede basarse en una plantilla Kit (opcional) o armarse libre.
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, null=True, blank=True,
                                related_name='cajas')
    kit = models.ForeignKey(Kit, related_name='instancias', on_delete=models.PROTECT,
                            null=True, blank=True)
    nombre = models.CharField(max_length=255, blank=True, null=True,
                              help_text="Nombre descriptivo de la caja (cajas libres sin plantilla)")
    codigo_caja = models.CharField(max_length=30)
    sucursal_actual = models.ForeignKey(Sucursal, on_delete=models.PROTECT)

    # Propiedad de la caja: propia (sale de tu inventario) o de consignación de un tercero.
    propiedad = models.CharField(max_length=10, choices=PROPIEDAD_CHOICES, default=PROPIEDAD_PROPIO)
    consignante = models.ForeignKey(Consignante, on_delete=models.PROTECT, null=True, blank=True,
                                    related_name='cajas')

    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES, default='DISPONIBLE')
    # La caja es un contenedor de stock: su contenido vive en esta ubicación.
    ubicacion = models.OneToOneField(
        'Ubicacion', on_delete=models.SET_NULL, null=True, blank=True, related_name='caja')
    notas = models.TextField(blank=True, null=True)

    class Meta:
        unique_together = ('empresa', 'codigo_caja')
        verbose_name_plural = "Instancias de kit (cajas)"

    @property
    def empresa_efectiva(self):
        return self.empresa or (self.kit.empresa if self.kit_id else None)

    @property
    def nombre_display(self):
        return self.nombre or (self.kit.nombre if self.kit_id else self.codigo_caja)

    def lineas_objetivo(self):
        """[(producto, cantidad, es_retornable)] — receta propia (libre) o heredada del kit."""
        propias = list(self.lineas.select_related('producto'))
        if propias:
            return [(l.producto, l.cantidad_objetivo, l.es_retornable) for l in propias]
        if self.kit_id:
            return [(c.producto, c.cantidad_requerida, c.es_retornable)
                    for c in self.kit.componentes.select_related('producto')]
        return []

    def contenido(self):
        """Existencias actuales dentro de la caja (su ubicación)."""
        if not self.ubicacion_id:
            return Existencia.objects.none()
        return Existencia.objects.filter(ubicacion=self.ubicacion, cantidad__gt=0).select_related(
            'producto', 'lote', 'serie')

    def __str__(self):
        return f"{self.codigo_caja} ({self.nombre_display}) [{self.estado}]"


class ContenidoCaja(models.Model):
    """Receta propia de una caja armada libremente (sin plantilla Kit).
    Define qué debe contener la caja: consumibles y herramientas de renta."""
    caja = models.ForeignKey(InstanciaKit, related_name='lineas', on_delete=models.CASCADE)
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    cantidad_objetivo = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    es_retornable = models.BooleanField(
        default=False,
        help_text="True = herramienta/renta que regresa. False = consumible.")
    notas = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        unique_together = ('caja', 'producto')
        verbose_name_plural = "Contenido de cajas"

    def __str__(self):
        return f"{self.producto.sku} x{self.cantidad_objetivo}"


class SalidaKit(models.Model):
    """Un viaje de la caja al hospital/cliente."""
    ESTADO_CHOICES = [
        ('PREPARANDO', 'Preparando'),
        ('ENVIADA', 'Enviada'),
        ('EN_USO', 'En uso'),
        ('RETORNADA', 'Retornada'),
        ('CERRADA', 'Cerrada (usado facturado/vendido)'),
        ('CANCELADA', 'Cancelada'),
    ]

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    folio = models.CharField(max_length=20, blank=True)
    instancia_kit = models.ForeignKey(InstanciaKit, related_name='salidas', on_delete=models.PROTECT)
    sucursal_origen = models.ForeignKey(Sucursal, on_delete=models.PROTECT)

    # Propiedad de la caja: una salida lleva stock todo propio o todo a consignación, sin mezclar.
    propiedad = models.CharField(max_length=10, choices=PROPIEDAD_CHOICES, default=PROPIEDAD_PROPIO)
    consignante = models.ForeignKey(Consignante, on_delete=models.PROTECT, null=True, blank=True)

    # Cliente formal al que se le liquidará la cirugía (genera el pedido/CxC)
    cliente = models.ForeignKey('admon_ventas.Cliente', on_delete=models.PROTECT, null=True, blank=True)
    # Pedido generado al liquidar (se llena en la liquidación)
    pedido_generado = models.ForeignKey('admon_ventas.Pedido', on_delete=models.SET_NULL,
                                        null=True, blank=True, related_name='salidas_kit')

    # Datos del destino/uso (cliente formal vendrá con módulo de ventas)
    hospital_cliente = models.CharField(max_length=255)
    doctor_responsable = models.CharField(max_length=255, blank=True, null=True)
    numero_cirugia = models.CharField(max_length=50, blank=True, null=True)
    paciente_referencia = models.CharField(max_length=100, blank=True, null=True,
                                           help_text="Referencia interna, no datos sensibles")

    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES, default='PREPARANDO')

    fecha_salida = models.DateTimeField(null=True, blank=True)
    fecha_retorno_esperada = models.DateField(null=True, blank=True)
    fecha_retorno_real = models.DateTimeField(null=True, blank=True)

    creado_por = models.ForeignKey(User, on_delete=models.PROTECT, related_name='salidas_kit_creadas')
    retorno_procesado_por = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True,
                                              related_name='retornos_kit_procesados')
    notas = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-fecha_salida']
        verbose_name_plural = "Salidas de kit"

    def save(self, *args, **kwargs):
        if not self.folio:
            ultimo = SalidaKit.objects.filter(empresa=self.empresa).count() + 1
            self.folio = f"SAL-{ultimo:05d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.folio}: {self.instancia_kit.codigo_caja} → {self.hospital_cliente} [{self.estado}]"


class ContenidoSalidaKit(models.Model):
    """Qué salió exactamente en la caja en este viaje, con trazabilidad total."""
    salida = models.ForeignKey(SalidaKit, related_name='contenido', on_delete=models.CASCADE)
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    lote = models.ForeignKey(Lote, on_delete=models.PROTECT, null=True, blank=True)
    serie = models.ForeignKey(NumeroSerie, on_delete=models.PROTECT, null=True, blank=True)
    ubicacion_origen = models.ForeignKey(Ubicacion, on_delete=models.PROTECT,
                                         help_text="De dónde se tomó (y a dónde regresa lo no usado)")

    # Snapshot de la propiedad del stock que salió en esta partida
    propiedad = models.CharField(max_length=10, choices=PROPIEDAD_CHOICES, default=PROPIEDAD_PROPIO)
    consignante = models.ForeignKey(Consignante, on_delete=models.PROTECT, null=True, blank=True)

    es_retornable = models.BooleanField(default=False)
    cantidad_enviada = models.DecimalField(max_digits=12, decimal_places=4)
    cantidad_retornada = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    cantidad_usada = models.DecimalField(max_digits=12, decimal_places=4, default=0,
                                         help_text="enviada - retornada (lo que se factura)")

    @property
    def importe_usado(self):
        return self.cantidad_usada * self.producto.precio_venta

    def __str__(self):
        return f"{self.producto.sku} env:{self.cantidad_enviada} ret:{self.cantidad_retornada} uso:{self.cantidad_usada}"
