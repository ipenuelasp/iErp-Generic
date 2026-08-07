from django.urls import path
from . import views

app_name = 'admon_comunes'

urlpatterns = [
    path('notificaciones/<int:pk>/abrir/', views.abrir_notificacion, name='abrir_notificacion'),
    path('notificaciones/marcar-leidas/', views.marcar_todas_leidas, name='marcar_leidas'),
]
