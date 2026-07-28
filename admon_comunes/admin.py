from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Adjunto


@admin.register(Adjunto)
class AdjuntoAdmin(ModelAdmin):
    list_display = ('nombre_original', 'empresa', 'content_type', 'object_id',
                    'tamano_legible', 'estado_scan', 'subido_en')
    list_filter = ('empresa', 'estado_scan', 'es_imagen')
    search_fields = ('nombre_original', 'hash_sha256')
    readonly_fields = ('subido_en',)
