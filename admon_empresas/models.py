from django.db import models
from django.contrib.auth.models import User

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
import uuid
import io

import resend
from django.conf import settings
from django.urls import reverse

from django.template.loader import render_to_string
from django.utils.html import strip_tags

class ClienteSaaS(models.Model):
    """ Representa al dueño del contrato (El suscriptor) """
    nombre_comercial = models.CharField(max_length=255)
    # Identificador único para el despliegue en Digital Ocean
    slug_instancia = models.SlugField(unique=True) 
    email_contacto = models.EmailField(null=True, blank=True) # <-- Nuevo campo
    token_invitacion = models.UUIDField(default=uuid.uuid4, editable=False) # Para el link seguro
    registro_completado = models.BooleanField(default=False)
    fecha_registro = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nombre_comercial

class Empresa(models.Model):
    """ Un ClienteSaaS puede tener varias razones sociales (RFCs) """
    cliente = models.ForeignKey(ClienteSaaS, on_delete=models.CASCADE, related_name='empresas')
    nombre_fiscal = models.CharField(max_length=255)
    logo = models.ImageField(upload_to='logos/', null=True, blank=True)
    isotipo = models.ImageField(upload_to='isotipos/', null=True, blank=True,
                                help_text="Solo el emblema (cuadrado), para vistas compactas/favicon.")
    moneda_principal = models.ForeignKey('Moneda', on_delete=models.SET_NULL, null=True, blank=True, related_name='empresa_base')
    decimales_permitidos = models.PositiveIntegerField(default=2)
    rfc = models.CharField(max_length=20, unique=True)
    
    autoguardado_intervalo = models.PositiveIntegerField(
        default=60, 
        help_text="Intervalo en segundos para el autoguardado de documentos."
    )
    
    COLOR_CHOICES = [
        ('indigo', 'Indigo Moderno'),
        ('blue', 'Azul Corporativo'),
        ('emerald', 'Verde Ecológico'),
        ('rose', 'Rosa Elegante'),
        ('slate', 'Gris Profesional'),
    ]
    color_primario = models.CharField(max_length=20, choices=COLOR_CHOICES, default='indigo')

    TEMA_ERROR_CHOICES = [
        ('robot', 'Robot (formal / médico)'),
        ('alien', 'Alien (informal / divertido)'),
    ]
    tema_error = models.CharField(
        "Tema de página de error", max_length=10, choices=TEMA_ERROR_CHOICES, default='robot',
        help_text="Estilo de la página amigable que se muestra ante errores o mantenimiento.")

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.logo:
            self._autocrop_logo()

    def _autocrop_logo(self):
        try:
            from PIL import Image
            path = self.logo.path
            img = Image.open(path).convert('RGBA')
            # Recortar por el canal alpha (transparencia) si existe contenido visible
            r, g, b, alpha = img.split()
            bbox = alpha.getbbox()
            if not bbox:
                # Sin transparencia — recortar por diferencia con fondo blanco
                from PIL import ImageChops
                bg = Image.new('RGBA', img.size, (255, 255, 255, 255))
                diff = ImageChops.difference(img, bg)
                bbox = diff.getbbox()
            if bbox:
                img = img.crop(bbox)
            img.save(path, format='PNG', optimize=True)
        except Exception as e:
            print(f'[LOGO CROP] {e}')

    def __str__(self):
        return f"{self.nombre_fiscal} ({self.cliente.nombre_comercial})"

class Sucursal(models.Model):
    """ La unidad operativa final donde se realizan las transacciones """
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='sucursales')
    nombre = models.CharField(max_length=255)
    es_matriz = models.BooleanField(default=False)
    # Configuración específica para SQL Server o integraciones
    codigo_sucursal = models.CharField(max_length=10)     

    def __str__(self):
        return f"{self.nombre} - {self.empresa.nombre_fiscal}"   

class PerfilUsuario(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='perfil')
    
    nombre = models.CharField(max_length=100, blank=True)
    apellido = models.CharField(max_length=100, blank=True)
    # Relación con su "casa matriz" o empresa asignada
    empresas = models.ManyToManyField(Empresa, related_name='empleados')
    # Podemos dejar una "empresa_principal" para el login inicial
    empresa_default = models.ForeignKey(Empresa, on_delete=models.SET_NULL, null=True, blank=True)
    
    sucursal_defecto = models.ForeignKey(Sucursal, on_delete=models.SET_NULL, null=True, blank=True)

    sucursales = models.ManyToManyField(Sucursal, blank=True, related_name='usuarios_permitidos')
    
    # Roles para tu lógica de negocio
    ES_DUENO = 'OWNER'
    ES_GERENTE = 'MANAGER'
    ES_OPERADOR = 'OPERATOR'
    
    TIPO_USUARIO_CHOICES = [
        (ES_DUENO, 'Dueño de Empresa'),
        (ES_GERENTE, 'Gerente de Sucursal'),
        (ES_OPERADOR, 'Operador / Staff'),
    ]
    
    tipo_usuario = models.CharField(
        max_length=20, 
        choices=TIPO_USUARIO_CHOICES, 
        default=ES_OPERADOR
    )

    puede_gestionar_usuarios = models.BooleanField(
        default=False, 
        help_text="Permite al dueño crear y editar usuarios de su propia empresa."
    )

    invitacion_aceptada = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username} - {self.tipo_usuario}"
    
class Moneda(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='monedas_empresa')
    nombre = models.CharField(max_length=50) # Ej: Peso Mexicano
    codigo = models.CharField(max_length=3) # Ej: MXN
    simbolo = models.CharField(max_length=5, default='$')
    es_principal = models.BooleanField(default=False)
    activa = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.nombre} ({self.codigo})"


class Impuesto(models.Model):
    """Catálogo fiscal configurable por empresa. Lo usan compras, ventas
    y la facturación futura. Soporta traslados (suman) y retenciones (restan)."""
    TIPO_TASA = 'TASA'
    TIPO_EXENTO = 'EXENTO'
    TIPO_FACTOR_CHOICES = [
        (TIPO_TASA, 'Tasa'),
        (TIPO_EXENTO, 'Exento'),
    ]

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='impuestos')
    nombre = models.CharField(max_length=60, help_text="Ej: IVA 16%, Retención 6.25%, Exento")
    tasa = models.DecimalField(max_digits=7, decimal_places=4, default=0,
                               help_text="Porcentaje. Ej: 16, 8, 0, 6.25")
    tipo_factor = models.CharField(max_length=10, choices=TIPO_FACTOR_CHOICES, default=TIPO_TASA)
    es_retencion = models.BooleanField(default=False, help_text="Si se marca, resta del total en vez de sumar.")
    # Clave SAT para CFDI futuro (002=IVA, 001=ISR, 003=IEPS)
    clave_sat = models.CharField(max_length=10, blank=True, null=True)

    es_default = models.BooleanField(default=False, help_text="Se aplica cuando un producto no tiene impuesto asignado.")
    activo = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['orden', 'nombre']
        verbose_name = "Impuesto"
        verbose_name_plural = "Impuestos"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Solo un default por empresa
        if self.es_default:
            Impuesto.objects.filter(empresa=self.empresa, es_default=True).exclude(pk=self.pk).update(es_default=False)

    def __str__(self):
        return self.nombre


class EmpresaModulo(models.Model):
    """Módulos contratados/habilitados para una empresa (Capa 1, la define el super admin)."""
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='modulos')
    modulo = models.CharField(max_length=30)
    activo = models.BooleanField(default=True)

    class Meta:
        unique_together = ('empresa', 'modulo')

    def __str__(self):
        return f"{self.empresa.nombre_fiscal} · {self.modulo} ({'on' if self.activo else 'off'})"


class AccesoModuloUsuario(models.Model):
    """Módulos que un usuario puede ver dentro de una empresa (Capa 2, la define el dueño)."""
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='accesos_modulo')
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    modulo = models.CharField(max_length=30)

    class Meta:
        unique_together = ('usuario', 'empresa', 'modulo')

    def __str__(self):
        return f"{self.usuario.username} · {self.empresa_id} · {self.modulo}"


class SeccionOcultaUsuario(models.Model):
    """Pantallas/ligas OCULTAS a un usuario dentro de un módulo (Capa 3, permiso fino).
    Blocklist: si una sección está aquí, el usuario NO la ve ni puede entrar.
    Por defecto (sin registros) ve todas las secciones de sus módulos."""
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='secciones_ocultas')
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    seccion = models.CharField(max_length=50)  # clave de la sección (ver modulos.SECCIONES)

    class Meta:
        unique_together = ('usuario', 'empresa', 'seccion')

    def __str__(self):
        return f"{self.usuario.username} · oculta {self.seccion}"


@receiver(post_save, sender=User)
def crear_perfil_usuario(sender, instance, created, **kwargs):
    if created:
        PerfilUsuario.objects.create(user=instance)

@receiver(post_save, sender=User)
def guardar_perfil_usuario(sender, instance, **kwargs):
    instance.perfil.save()

@receiver(post_save, sender=ClienteSaaS)
def enviar_invitacion_cliente(sender, instance, created, **kwargs):
    if created and instance.email_contacto:
        from admon_empresas.emails import enviar_invitacion_cliente as _enviar
        _enviar(instance)

@receiver(post_save, sender=Empresa)
def asignar_superusers_a_empresa(sender, instance, created, **kwargs):
    if not created:
        return
    superusers = User.objects.filter(is_superuser=True)
    for su in superusers:
        perfil = su.perfil
        perfil.empresas.add(instance)
        if not perfil.empresa_default:
            perfil.empresa_default = instance
            perfil.save()


@receiver(post_save, sender=Empresa)
def crear_impuestos_base(sender, instance, created, **kwargs):
    """Siembra el catálogo fiscal mexicano básico al crear una empresa."""
    if not created:
        return
    base = [
        ('IVA 16%', 16, 'TASA', False, True, '002', 1),
        ('IVA 8% (frontera)', 8, 'TASA', False, False, '002', 2),
        ('Tasa 0%', 0, 'TASA', False, False, '002', 3),
        ('Exento', 0, 'EXENTO', False, False, '002', 4),
    ]
    for nombre, tasa, factor, ret, default, clave, orden in base:
        Impuesto.objects.create(
            empresa=instance, nombre=nombre, tasa=tasa, tipo_factor=factor,
            es_retencion=ret, es_default=default, clave_sat=clave, orden=orden)


@receiver(post_save, sender=Empresa)
def crear_metodos_pago_base(sender, instance, created, **kwargs):
    """Siembra métodos de pago básicos al crear una empresa."""
    if not created:
        return
    from admon_finanzas.models import MetodoPago
    for nombre, clave in [('Efectivo', '01'), ('Transferencia', '03'),
                          ('Cheque', '02'), ('Tarjeta', '04')]:
        MetodoPago.objects.create(empresa=instance, nombre=nombre, clave_sat=clave)


@receiver(post_save, sender=Empresa)
def habilitar_modulos_base(sender, instance, created, **kwargs):
    """Una empresa nace con todos los módulos disponibles activos.
    El super admin desactiva los que no apliquen (ej. Insermed → Producción off)."""
    if not created:
        return
    from .modulos import MODULOS_DISPONIBLES
    for m in MODULOS_DISPONIBLES:
        EmpresaModulo.objects.get_or_create(
            empresa=instance, modulo=m['clave'], defaults={'activo': True})


@receiver(post_save, sender=Sucursal)
def asignar_superusers_a_sucursal(sender, instance, created, **kwargs):
    if not created:
        return
    superusers = User.objects.filter(is_superuser=True)
    for su in superusers:
        perfil = su.perfil
        perfil.sucursales.add(instance)
        if not perfil.sucursal_defecto:
            perfil.sucursal_defecto = instance
            perfil.save()


@receiver(post_delete, sender=ClienteSaaS)
def limpiar_usuarios_cliente(sender, instance, **kwargs):
    """Al borrar un cliente, elimina todos sus usuarios no-superuser."""
    usuarios = User.objects.filter(
        perfil__empresas__cliente=instance,
        is_superuser=False
    ).distinct()
    count = usuarios.count()
    usuarios.delete()
    if count:
        print(f'[CLEANUP] {count} usuario(s) eliminados al borrar cliente: {instance.nombre_comercial}')