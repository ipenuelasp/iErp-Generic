from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from .models import MetodoPago, FacturaProveedor, Pago, AplicacionPago


@admin.register(MetodoPago)
class MetodoPagoAdmin(ModelAdmin):
    list_display = ('nombre', 'empresa', 'clave_sat', 'activo')
    list_filter = ('empresa', 'activo')


@admin.register(FacturaProveedor)
class FacturaProveedorAdmin(ModelAdmin):
    list_display = ('folio', 'proveedor', 'orden_compra', 'total', 'estado', 'fecha_emision')
    list_filter = ('estado', 'empresa')
    search_fields = ('folio', 'uuid_cfdi')


class AplicacionPagoInline(TabularInline):
    model = AplicacionPago
    extra = 0


@admin.register(Pago)
class PagoAdmin(ModelAdmin):
    list_display = ('folio', 'tipo', 'proveedor', 'monto', 'moneda', 'fecha', 'metodo')
    list_filter = ('tipo', 'empresa')
    inlines = [AplicacionPagoInline]
