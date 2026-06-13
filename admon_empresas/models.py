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
        from admon_empresas.emails import send_html, _build_url
        import base64, os
        url_registro = f"{settings.SITE_URL}/registro-cliente/{instance.token_invitacion}/"
        # Logo iErp en base64 para que se vea en cualquier cliente de correo
        logo_url = ''
        try:
            path = os.path.join(settings.BASE_DIR, 'static', 'img', 'iErp_4k_sinfondo.png')
            with open(path, 'rb') as f:
                logo_url = f'data:image/png;base64,{base64.b64encode(f.read()).decode()}'
        except Exception:
            pass
        send_html(
            subject=f"Bienvenido a iErp — Configura tu empresa: {instance.nombre_comercial}",
            template='admon_empresas/emails/bienvenida_cliente.html',
            context={
                'nombre_comercial': instance.nombre_comercial,
                'url_registro': url_registro,
                'logo_url': logo_url,
            },
            to=instance.email_contacto,
        )

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