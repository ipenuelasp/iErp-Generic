from django.contrib import admin
from .models import (Cliente, Pedido, DetallePedido, ComisionPedido,
                     Cotizacion, DetalleCotizacion)


class DetallePedidoInline(admin.TabularInline):
    model = DetallePedido
    extra = 0


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ('nombre_fiscal', 'rfc', 'empresa', 'activo')
    list_filter = ('empresa', 'activo')
    search_fields = ('nombre_fiscal', 'nombre_comercial', 'rfc')


class ComisionPedidoInline(admin.TabularInline):
    model = ComisionPedido
    extra = 0


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ('folio', 'cliente', 'estado', 'origen', 'total', 'fecha_emision')
    list_filter = ('empresa', 'estado', 'origen')
    search_fields = ('folio',)
    inlines = [DetallePedidoInline, ComisionPedidoInline]


class DetalleCotizacionInline(admin.TabularInline):
    model = DetalleCotizacion
    extra = 0


@admin.register(Cotizacion)
class CotizacionAdmin(admin.ModelAdmin):
    list_display = ('folio', 'cliente', 'estado', 'total', 'fecha_emision')
    list_filter = ('empresa', 'estado')
    search_fields = ('folio',)
    inlines = [DetalleCotizacionInline]
