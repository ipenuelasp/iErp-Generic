from django.urls import path
from . import views

urlpatterns = [
    path('gestion-usuarios/', views.gestion_usuarios, name='gestion_usuarios'),
    path('crear-usuario/', views.crear_usuario, name='crear_usuario'),
    path('editar-usuario/<int:usuario_id>/', views.editar_usuario, name='editar_usuario'),
    
    path('reenviar-invitacion/<int:usuario_id>/', views.reenviar_invitacion, name='reenviar_invitacion'),
    path('usuario/<int:usuario_id>/toggle-activo/', views.toggle_activo_usuario, name='toggle_activo_usuario'),
    path('configuracion/cambiar-password/', views.cambiar_password_obligatorio, name='cambiar_password_obligatorio'),
    
]