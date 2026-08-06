from django.urls import path
from . import views

app_name = 'admon_tareas'

urlpatterns = [
    path('', views.TablerosView.as_view(), name='tableros'),
    path('mis-tareas/', views.MisTareasView.as_view(), name='mis_tareas'),
    path('movil/', views.MovilView.as_view(), name='movil'),
    path('tablero/<int:pk>/', views.TableroDetalleView.as_view(), name='tablero_detalle'),
    path('tarea/<int:pk>/panel/', views.TareaPanelView.as_view(), name='tarea_panel'),
    path('adjunto/<int:pk>/', views.AdjuntoDescargaView.as_view(), name='adjunto_descarga'),
]
