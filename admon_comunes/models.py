"""
App 'comunes': piezas transversales reutilizables por todo el ERP.

Por ahora solo el Adjunto genérico (archivos colgados de cualquier modelo vía
GenericForeignKey). Un solo modelo de adjunto para todo el sistema: se cuelga de
Tarea, TareaComentario, TareaActividad hoy, y de cualquier entidad mañana sin
migración nueva.
"""
import os
import uuid

from django.db import models
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType

from admon_empresas.models import Empresa


def ruta_adjunto(instance, filename):
    """Nunca el nombre original en disco. Aislado por empresa para que el prefijo
    del bucket sea el límite de tenant."""
    ext = os.path.splitext(filename)[1].lower()[:12]
    return f"adjuntos/{instance.empresa_id}/{uuid.uuid4().hex}{ext}"


class Adjunto(models.Model):
    """Adjunto genérico. Se cuelga de cualquier modelo vía GenericForeignKey."""
    ESTADO_SCAN = [
        ('PEND', 'Pendiente de análisis'),
        ('LIMPIO', 'Limpio'),
        ('INFECTADO', 'Infectado'),
        ('ERROR', 'Error al analizar'),
    ]

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='adjuntos')
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    contenido = GenericForeignKey('content_type', 'object_id')

    archivo = models.FileField(upload_to=ruta_adjunto, max_length=500)
    nombre_original = models.CharField('Nombre', max_length=255)
    extension = models.CharField(max_length=12, blank=True)
    mime_detectado = models.CharField(max_length=120, blank=True)
    tamano_bytes = models.BigIntegerField(default=0)
    hash_sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    es_imagen = models.BooleanField(default=False)
    thumbnail = models.ImageField(upload_to=ruta_adjunto, max_length=500, null=True, blank=True)
    estado_scan = models.CharField(max_length=9, choices=ESTADO_SCAN, default='PEND')

    subido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    subido_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'comunes_adjunto'
        verbose_name = 'Adjunto'
        verbose_name_plural = 'Adjuntos'
        ordering = ('-subido_en',)
        indexes = [
            models.Index(fields=['content_type', 'object_id']),
            models.Index(fields=['empresa', 'subido_en']),
        ]

    def __str__(self):
        return self.nombre_original

    @property
    def tamano_legible(self):
        n = float(self.tamano_bytes)
        for u in ('B', 'KB', 'MB', 'GB'):
            if n < 1024:
                return f"{n:.0f} {u}" if u == 'B' else f"{n:.1f} {u}"
            n /= 1024
        return f"{n:.1f} TB"

    @property
    def puede_previsualizar(self):
        """Solo imágenes y PDF se abren inline. Todo lo demás se descarga."""
        return self.mime_detectado in (
            'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'application/pdf'
        ) and self.estado_scan in ('LIMPIO', 'PEND')


class AdjuntableMixin(models.Model):
    """Hereda esto en cualquier modelo que deba aceptar archivos."""
    adjuntos = GenericRelation(Adjunto, related_query_name='%(class)s')

    class Meta:
        abstract = True


class Notificacion(models.Model):
    """Notificación in-app para un usuario. Transversal: cualquier módulo la crea.
    Hoy solo en el sistema; más adelante se puede disparar también por correo."""
    TIPOS = [
        ('ASIGNACION', 'Asignación'),
        ('COMENTARIO', 'Comentario'),
        ('ESTADO', 'Cambio de estado'),
        ('BLOQUEO', 'Bloqueo'),
        ('GENERAL', 'General'),
    ]
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name='notificaciones')
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, null=True, blank=True,
                                related_name='notificaciones')
    tipo = models.CharField(max_length=12, choices=TIPOS, default='GENERAL')
    titulo = models.CharField(max_length=180)
    mensaje = models.CharField(max_length=500, blank=True)
    url = models.CharField(max_length=300, blank=True)
    icono = models.CharField(max_length=30, blank=True)   # clase FontAwesome
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                              null=True, blank=True, related_name='notificaciones_generadas')
    leida = models.BooleanField(default=False)
    leida_en = models.DateTimeField(null=True, blank=True)
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'comunes_notificacion'
        ordering = ('-creada_en',)
        indexes = [
            models.Index(fields=['usuario', 'leida']),
            models.Index(fields=['usuario', '-creada_en']),
        ]

    def __str__(self):
        return f"{self.usuario} · {self.titulo}"

    @classmethod
    def crear(cls, *, usuario, titulo, mensaje='', url='', tipo='GENERAL',
              icono='', empresa=None, actor=None):
        """Crea una notificación. No te notifica a ti mismo (actor == usuario)."""
        if usuario is None or (actor is not None and actor.id == usuario.id):
            return None
        return cls.objects.create(
            usuario=usuario, empresa=empresa, tipo=tipo, titulo=titulo[:180],
            mensaje=(mensaje or '')[:500], url=url[:300], icono=icono, actor=actor)
