"""
Módulo de Tareas y Proyectos (contratable extra).

Contenedor = Tablero (NUNCA 'Proyecto', nombre reservado). Tres relaciones
distintas en tres tablas: jerarquía (Tarea.padre + ruta_wbs), dependencia
(TareaDependencia, puede cruzar tableros), asignación (TareaAsignacion, con
confirmación por persona). La lógica derivada (avance, cierre, WBS, bloqueos)
vive en services.py — nunca en señales. Ver docs/modulo_tareas/.

Fase 1: modelos + migraciones. Sin UI ni lógica de negocio todavía.
"""
from django.db import models
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from admon_empresas.models import Empresa
from admon_comunes.models import AdjuntableMixin


# Tipos de tablero que se siembran por empresa la primera vez (editables después).
DEFAULT_TIPOS = ['Arranque', 'Implementación', 'Soporte', 'Mejora', 'Interno']


class TipoTablero(models.Model):
    """Catálogo modificable de tipos de tablero, por empresa."""
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='tipos_tablero')
    nombre = models.CharField(max_length=60)
    orden = models.IntegerField(default=0)
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tareas_tipotablero'
        verbose_name = 'Tipo de tablero'
        verbose_name_plural = 'Tipos de tablero'
        ordering = ('orden', 'nombre')
        constraints = [
            models.UniqueConstraint(fields=['empresa', 'nombre'], name='uq_tipotablero_empresa_nombre'),
        ]

    def __str__(self):
        return self.nombre


def tipos_de(empresa):
    """Devuelve (sembrando la primera vez) los tipos de tablero activos de la empresa."""
    qs = TipoTablero.objects.filter(empresa=empresa)
    if not qs.exists():
        TipoTablero.objects.bulk_create(
            [TipoTablero(empresa=empresa, nombre=n, orden=i)
             for i, n in enumerate(DEFAULT_TIPOS)])
        qs = TipoTablero.objects.filter(empresa=empresa)
    return qs.filter(activo=True)


class TableroQuerySet(models.QuerySet):
    def operativos(self):
        """Tableros de trabajo real. Excluye plantillas."""
        return self.filter(es_plantilla=False)

    def plantillas_para(self, empresa):
        """Plantillas instanciables en esta empresa: las suyas + el catálogo global."""
        return self.filter(es_plantilla=True, activo=True).filter(
            models.Q(empresa=empresa) | models.Q(alcance='GLOBAL'))


class Tablero(models.Model):
    """Contenedor de tareas. Define el modo de cierre y la ventana de fechas.
    Con es_plantilla=True funciona como molde instanciable (mismo modelo)."""
    MODO_CIERRE = [
        ('TODOS', 'Todos los asignados confirman'),
        ('RESPONSABLE', 'Solo el responsable cierra'),
        ('CUALQUIERA', 'El primero que confirme'),
    ]
    ALCANCE = [
        ('EMPRESA', 'Solo esta empresa'),
        ('GLOBAL', 'Catálogo del proveedor'),
    ]

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='tableros')
    codigo = models.CharField(max_length=20)
    nombre = models.CharField(max_length=180)
    descripcion = models.TextField(blank=True)
    tipo = models.ForeignKey(TipoTablero, on_delete=models.PROTECT, null=True, blank=True,
                             related_name='tableros')
    modo_cierre = models.CharField(max_length=12, choices=MODO_CIERRE, default='TODOS')
    responsable = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name='tableros_a_cargo')
    fecha_inicio = models.DateField(null=True, blank=True)
    fecha_fin = models.DateField(null=True, blank=True)
    color = models.CharField(max_length=7, default='#4f46e5')
    activo = models.BooleanField(default=True)

    # ---- Plantillas ----
    es_plantilla = models.BooleanField(
        'Es plantilla', default=False,
        help_text='Un tablero plantilla no se trabaja: sirve de molde para crear otros.')
    alcance = models.CharField(max_length=7, choices=ALCANCE, default='EMPRESA')
    plantilla_origen = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='instancias', editable=False,
        help_text='Plantilla de la que salió este tablero.')
    instanciado_en = models.DateTimeField(null=True, blank=True, editable=False)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='tableros_creados')

    objects = TableroQuerySet.as_manager()

    class Meta:
        db_table = 'tareas_tablero'
        verbose_name = 'Tablero'
        verbose_name_plural = 'Tableros'
        ordering = ('nombre',)
        constraints = [
            models.UniqueConstraint(fields=['empresa', 'codigo'], name='uq_tablero_codigo'),
            models.CheckConstraint(
                check=models.Q(es_plantilla=False) | models.Q(plantilla_origen__isnull=True),
                name='ck_tablero_plt_origen'),
        ]
        permissions = [
            ('gestionar_plantillas_globales',
             'Puede crear plantillas globales e instanciarlas en cualquier empresa'),
        ]

    def __str__(self):
        etq = ' [plantilla]' if self.es_plantilla else ''
        return f"{self.codigo} · {self.nombre}{etq}"

    def clean(self):
        if self.es_plantilla and self.plantilla_origen_id:
            raise ValidationError(
                {'es_plantilla': 'Una plantilla no puede a su vez ser instancia de otra.'})


class Seccion(models.Model):
    """Agrupador visual (columnas/grupos del kanban) dentro de un tablero."""
    tablero = models.ForeignKey(Tablero, on_delete=models.CASCADE, related_name='secciones')
    nombre = models.CharField(max_length=80)
    orden = models.IntegerField(default=0)

    class Meta:
        db_table = 'tareas_seccion'
        verbose_name = 'Sección'
        verbose_name_plural = 'Secciones'
        ordering = ('orden', 'nombre')

    def __str__(self):
        return self.nombre


class Etiqueta(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='etiquetas_tarea')
    nombre = models.CharField(max_length=50)
    color = models.CharField(max_length=7, default='#6b7280')

    class Meta:
        db_table = 'tareas_etiqueta'
        verbose_name = 'Etiqueta'
        verbose_name_plural = 'Etiquetas'
        ordering = ('nombre',)
        constraints = [
            models.UniqueConstraint(fields=['empresa', 'nombre'], name='uq_etiqueta_empresa_nombre'),
        ]

    def __str__(self):
        return self.nombre


class Tarea(AdjuntableMixin):
    """Entidad central. Jerárquica (WBS) y, opcionalmente, ligada a un registro
    del ERP (OC, ticket, estimación…) vía GenericForeignKey."""
    ESTADO = [
        ('PEND', 'Pendiente'), ('PROC', 'En proceso'), ('BLOQ', 'Bloqueada'),
        ('REVI', 'En revisión'), ('COMP', 'Completada'), ('CANC', 'Cancelada'),
    ]
    PRIORIDAD = [('BAJA', 'Baja'), ('MEDIA', 'Media'), ('ALTA', 'Alta'), ('URGE', 'Urgente')]

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='tareas')
    tablero = models.ForeignKey(Tablero, on_delete=models.CASCADE, related_name='tareas')
    seccion = models.ForeignKey(Seccion, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='tareas')
    padre = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True,
                              related_name='hijos')

    folio = models.CharField(max_length=13, editable=False, blank=True)   # TSK0000000001
    ruta_wbs = models.CharField(max_length=60, editable=False, default='', blank=True)  # '2.1.3'
    nivel = models.SmallIntegerField(default=0, editable=False)
    orden = models.IntegerField(default=0)

    titulo = models.CharField(max_length=255)
    descripcion = models.TextField(blank=True)
    estado = models.CharField(max_length=4, choices=ESTADO, default='PEND', db_index=True)
    prioridad = models.CharField(max_length=5, choices=PRIORIDAD, default='MEDIA')
    perfil_sugerido = models.CharField(
        'Perfil sugerido', max_length=80, blank=True,
        help_text="Solo se usa en plantillas. Ej: 'Consultor funcional', 'Contacto del cliente'.")

    fecha_inicio_plan = models.DateField(null=True, blank=True)
    fecha_fin_plan = models.DateField(null=True, blank=True)
    fecha_inicio_real = models.DateField(null=True, blank=True)
    fecha_fin_real = models.DateField(null=True, blank=True)
    duracion_dias = models.IntegerField(null=True, blank=True)
    duracion_horas = models.PositiveSmallIntegerField(default=0)

    avance = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    peso = models.DecimalField(max_digits=6, decimal_places=2, default=1)
    es_hito = models.BooleanField('Es hito', default=False)
    es_resumen = models.BooleanField(default=False, editable=False)
    es_bloqueante = models.BooleanField(default=False, editable=False)

    # Vínculo opcional a cualquier registro del ERP
    origen_ct = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    origen_obj_id = models.PositiveIntegerField(null=True, blank=True)
    origen = GenericForeignKey('origen_ct', 'origen_obj_id')

    etiquetas = models.ManyToManyField(Etiqueta, blank=True, related_name='tareas')

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='tareas_creadas')
    cerrado_en = models.DateTimeField(null=True, blank=True)
    cerrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name='tareas_cerradas')

    class Meta:
        db_table = 'tareas_tarea'
        verbose_name = 'Tarea'
        verbose_name_plural = 'Tareas'
        ordering = ('tablero', 'orden', 'ruta_wbs')
        constraints = [
            models.UniqueConstraint(fields=['empresa', 'folio'], name='uq_tarea_folio'),
            models.CheckConstraint(check=models.Q(avance__gte=0) & models.Q(avance__lte=100),
                                   name='ck_tarea_avance'),
        ]
        indexes = [
            models.Index(fields=['empresa', 'tablero', 'estado']),
            models.Index(fields=['padre']),
            models.Index(fields=['tablero', 'ruta_wbs']),
            models.Index(fields=['origen_ct', 'origen_obj_id']),
        ]

    def __str__(self):
        return f"{self.folio or 'TSK?'} · {self.titulo}"


class TareaAsignacion(models.Model):
    """M2M con datos: quién trabaja la tarea, su rol y si ya confirmó su parte.
    El estado de la tarea se deriva de estas confirmaciones + Tablero.modo_cierre."""
    ROL = [('RESP', 'Responsable'), ('COLA', 'Colaborador'), ('REVI', 'Revisor')]

    tarea = models.ForeignKey(Tarea, on_delete=models.CASCADE, related_name='asignaciones')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name='tareas_asignadas')
    rol = models.CharField(max_length=4, choices=ROL, default='COLA')
    completado = models.BooleanField(default=False)
    completado_en = models.DateTimeField(null=True, blank=True)
    nota_cierre = models.CharField(max_length=500, blank=True)
    asignado_en = models.DateTimeField(auto_now_add=True)
    asignado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name='asignaciones_hechas')

    class Meta:
        db_table = 'tareas_tareaasignacion'
        verbose_name = 'Asignación de tarea'
        verbose_name_plural = 'Asignaciones de tarea'
        constraints = [
            models.UniqueConstraint(fields=['tarea', 'usuario'], name='uq_asignacion_tarea_usuario'),
        ]
        indexes = [models.Index(fields=['usuario', 'completado'])]

    def __str__(self):
        return f"{self.tarea_id} → {self.usuario_id} ({self.rol})"


class TareaDependencia(models.Model):
    """Grafo dirigido entre tareas (puede cruzar tableros). Alimenta el Gantt y
    los bloqueos. origen='BLOQUEO' cuando se reporta en ejecución."""
    TIPO = [('FS', 'Fin → Inicio'), ('SS', 'Inicio → Inicio'),
            ('FF', 'Fin → Fin'), ('SF', 'Inicio → Fin')]
    ORIGEN = [('PLANEADA', 'Del cronograma'), ('BLOQUEO', 'Reportada en ejecución')]

    predecesora = models.ForeignKey(Tarea, on_delete=models.CASCADE, related_name='dependencias_salientes')
    sucesora = models.ForeignKey(Tarea, on_delete=models.CASCADE, related_name='dependencias_entrantes')
    tipo = models.CharField(max_length=2, choices=TIPO, default='FS')
    desfase_dias = models.IntegerField(default=0)
    origen = models.CharField(max_length=8, choices=ORIGEN, default='PLANEADA')
    motivo = models.TextField(blank=True)   # obligatorio si origen='BLOQUEO' (se valida en services)
    resuelta = models.BooleanField(default=False)
    resuelta_en = models.DateTimeField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='dependencias_creadas')

    class Meta:
        db_table = 'tareas_tareadependencia'
        verbose_name = 'Dependencia de tarea'
        verbose_name_plural = 'Dependencias de tarea'
        constraints = [
            models.UniqueConstraint(fields=['predecesora', 'sucesora'], name='uq_dependencia'),
            models.CheckConstraint(check=~models.Q(predecesora=models.F('sucesora')),
                                   name='ck_dependencia_no_self'),
        ]
        indexes = [
            models.Index(fields=['sucesora', 'resuelta']),
            models.Index(fields=['predecesora']),
        ]

    def __str__(self):
        return f"{self.predecesora_id} → {self.sucesora_id} [{self.tipo}]"


class TareaComentario(AdjuntableMixin):
    """Hilo de conversación de la tarea. Acepta adjuntos (mixin)."""
    tarea = models.ForeignKey(Tarea, on_delete=models.CASCADE, related_name='comentarios')
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name='comentarios_tarea')
    texto = models.TextField()
    editado = models.BooleanField(default=False)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tareas_tareacomentario'
        verbose_name = 'Comentario de tarea'
        verbose_name_plural = 'Comentarios de tarea'
        ordering = ('creado_en',)
        indexes = [models.Index(fields=['tarea', 'creado_en'])]

    def __str__(self):
        return f"Comentario {self.pk} de {self.tarea_id}"


class TareaActividad(AdjuntableMixin):
    """Bitácora inmutable de cambios de la tarea. Acepta adjuntos (mixin)."""
    tarea = models.ForeignKey(Tarea, on_delete=models.CASCADE, related_name='actividad')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                null=True, blank=True, related_name='actividad_tarea')
    accion = models.CharField(max_length=30)   # CREADA, ESTADO, ASIGNO, BLOQUEO, FECHA, AVANCE, ADJUNTO…
    campo = models.CharField(max_length=50, blank=True)
    valor_ant = models.CharField(max_length=500, blank=True)
    valor_nue = models.CharField(max_length=500, blank=True)
    detalle = models.TextField(blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tareas_tareaactividad'
        verbose_name = 'Actividad de tarea'
        verbose_name_plural = 'Actividad de tarea'
        ordering = ('-creado_en',)
        indexes = [models.Index(fields=['tarea', 'creado_en'])]

    def __str__(self):
        return f"{self.accion} · tarea {self.tarea_id}"
