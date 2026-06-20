from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from .models import (
    Proveedor, AutorizadorCompra, OrdenCompra, DetalleOrdenCompra, AutorizacionOC,
)


@admin.register(Proveedor)
class ProveedorAdmin(ModelAdmin):
    list_display = ('nombre_fiscal', 'nombre_comercial', 'rfc', 'empresa', 'activo')
    list_filter = ('empresa', 'activo')
    search_fields = ('nombre_fiscal', 'nombre_comercial', 'rfc')


@admin.register(AutorizadorCompra)
class AutorizadorCompraAdmin(ModelAdmin):
    list_display = ('usuario', 'empresa', 'monto_autorizado', 'supervisor', 'activo')
    list_filter = ('empresa', 'activo')


class DetalleOrdenCompraInline(TabularInline):
    model = DetalleOrdenCompra
    extra = 0


class AutorizacionOCInline(TabularInline):
    model = AutorizacionOC
    extra = 0


@admin.register(OrdenCompra)
class OrdenCompraAdmin(ModelAdmin):
    list_display = ('folio', 'proveedor', 'sucursal_destino', 'estado', 'total', 'autorizador_actual', 'fecha_emision')
    list_filter = ('estado', 'sucursal_destino')
    search_fields = ('folio',)
    inlines = [DetalleOrdenCompraInline, AutorizacionOCInline]
