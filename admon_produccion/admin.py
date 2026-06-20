from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from .models import Receta, DetalleReceta, OrdenProduccion, ConsumoProduccion


class DetalleRecetaInline(TabularInline):
    model = DetalleReceta
    extra = 0


@admin.register(Receta)
class RecetaAdmin(ModelAdmin):
    list_display = ('nombre', 'version', 'producto_terminado', 'rendimiento', 'activa')
    inlines = [DetalleRecetaInline]


@admin.register(OrdenProduccion)
class OrdenProduccionAdmin(ModelAdmin):
    list_display = ('folio', 'receta', 'cantidad_a_producir', 'estado', 'sucursal', 'responsable')
    list_filter = ('estado', 'sucursal')
