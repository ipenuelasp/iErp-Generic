from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from .models import (
    Clase, Grupo, Tipo, UnidadMedida, Almacen, Ubicacion,
    Producto, ProductoSucursal, Lote, NumeroSerie,
    Existencia, MovimientoInventario,
    RecepcionMaterial, DetalleRecepcion,
    SolicitudTraspaso, DetalleTraspaso,
    Kit, DetalleKit, InstanciaKit, SalidaKit, ContenidoSalidaKit,
    Consignante,
)


@admin.register(Consignante)
class ConsignanteAdmin(ModelAdmin):
    list_display = ('nombre', 'empresa', 'rfc', 'activo')
    list_filter = ('empresa', 'activo')
    search_fields = ('nombre', 'rfc')


@admin.register(Producto)
class ProductoAdmin(ModelAdmin):
    list_display = ('sku', 'nombre', 'empresa', 'alcance', 'es_loteable', 'es_serializable', 'activo')
    list_filter = ('empresa', 'alcance', 'es_loteable', 'es_serializable', 'activo')
    search_fields = ('sku', 'nombre', 'codigo_barras')


@admin.register(ProductoSucursal)
class ProductoSucursalAdmin(ModelAdmin):
    list_display = ('producto', 'sucursal', 'activo_en_sucursal', 'stock_minimo', 'punto_reorden')
    list_filter = ('sucursal',)


@admin.register(Existencia)
class ExistenciaAdmin(ModelAdmin):
    list_display = ('producto', 'sucursal', 'almacen', 'ubicacion', 'lote', 'serie', 'cantidad')
    list_filter = ('sucursal', 'almacen')
    search_fields = ('producto__sku', 'producto__nombre')


@admin.register(MovimientoInventario)
class MovimientoInventarioAdmin(ModelAdmin):
    list_display = ('fecha', 'tipo', 'origen', 'referencia', 'producto', 'cantidad', 'sucursal', 'usuario')
    list_filter = ('tipo', 'origen', 'sucursal')
    search_fields = ('producto__sku', 'referencia')


class DetalleRecepcionInline(TabularInline):
    model = DetalleRecepcion
    extra = 0


@admin.register(RecepcionMaterial)
class RecepcionMaterialAdmin(ModelAdmin):
    list_display = ('folio', 'sucursal', 'proveedor_nombre', 'fecha_recepcion', 'recibido_por')
    inlines = [DetalleRecepcionInline]


class DetalleTraspasoInline(TabularInline):
    model = DetalleTraspaso
    extra = 0


@admin.register(SolicitudTraspaso)
class SolicitudTraspasoAdmin(ModelAdmin):
    list_display = ('folio', 'sucursal_origen', 'sucursal_destino', 'estado', 'fecha_solicitud')
    list_filter = ('estado',)
    inlines = [DetalleTraspasoInline]


class DetalleKitInline(TabularInline):
    model = DetalleKit
    extra = 0


@admin.register(Kit)
class KitAdmin(ModelAdmin):
    list_display = ('codigo', 'nombre', 'empresa', 'activo')
    inlines = [DetalleKitInline]


@admin.register(InstanciaKit)
class InstanciaKitAdmin(ModelAdmin):
    list_display = ('codigo_caja', 'kit', 'sucursal_actual', 'estado')
    list_filter = ('estado', 'sucursal_actual')


class ContenidoSalidaKitInline(TabularInline):
    model = ContenidoSalidaKit
    extra = 0


@admin.register(SalidaKit)
class SalidaKitAdmin(ModelAdmin):
    list_display = ('folio', 'instancia_kit', 'hospital_cliente', 'estado', 'fecha_salida')
    list_filter = ('estado',)
    inlines = [ContenidoSalidaKitInline]


for m in (Clase, Grupo, Tipo, UnidadMedida, Almacen, Ubicacion, Lote, NumeroSerie):
    admin.site.register(m, ModelAdmin)
