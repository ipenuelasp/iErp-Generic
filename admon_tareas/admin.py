from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from .models import (
    Tablero, Seccion, Etiqueta, Tarea,
    TareaAsignacion, TareaDependencia, TareaComentario, TareaActividad,
)


class SeccionInline(TabularInline):
    model = Seccion
    extra = 0


class TareaAsignacionInline(TabularInline):
    model = TareaAsignacion
    extra = 0
    autocomplete_fields = ('usuario',)


@admin.register(Tablero)
class TableroAdmin(ModelAdmin):
    list_display = ('codigo', 'nombre', 'empresa', 'tipo', 'modo_cierre',
                    'es_plantilla', 'alcance', 'activo')
    list_filter = ('empresa', 'tipo', 'es_plantilla', 'alcance', 'activo')
    search_fields = ('codigo', 'nombre')
    inlines = [SeccionInline]


@admin.register(Tarea)
class TareaAdmin(ModelAdmin):
    list_display = ('folio', 'ruta_wbs', 'titulo', 'tablero', 'estado',
                    'prioridad', 'avance', 'es_hito', 'es_resumen')
    list_filter = ('empresa', 'tablero', 'estado', 'prioridad', 'es_hito', 'es_resumen')
    search_fields = ('folio', 'titulo', 'ruta_wbs')
    autocomplete_fields = ('tablero', 'padre')
    inlines = [TareaAsignacionInline]


@admin.register(Etiqueta)
class EtiquetaAdmin(ModelAdmin):
    list_display = ('nombre', 'empresa', 'color')
    list_filter = ('empresa',)
    search_fields = ('nombre',)


@admin.register(TareaDependencia)
class TareaDependenciaAdmin(ModelAdmin):
    list_display = ('predecesora', 'sucesora', 'tipo', 'origen', 'resuelta')
    list_filter = ('tipo', 'origen', 'resuelta')


@admin.register(TareaComentario)
class TareaComentarioAdmin(ModelAdmin):
    list_display = ('tarea', 'autor', 'creado_en', 'editado')
    search_fields = ('texto',)


@admin.register(TareaActividad)
class TareaActividadAdmin(ModelAdmin):
    list_display = ('tarea', 'accion', 'campo', 'usuario', 'creado_en')
    list_filter = ('accion',)
