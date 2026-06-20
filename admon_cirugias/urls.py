from django.urls import path
from . import views

app_name = 'admon_cirugias'

urlpatterns = [
    path('solicitudes/', views.SolicitudesView.as_view(), name='solicitudes'),
    path('solicitudes/nueva/', views.NuevaSolicitudView.as_view(), name='nueva_solicitud'),
    path('solicitudes/<int:pk>/', views.SolicitudDetalleView.as_view(), name='solicitud_detalle'),
    path('solicitudes/<int:pk>/regreso/<int:salida_id>/', views.RegresoSalidaView.as_view(), name='regreso_salida'),
    path('solicitudes/<int:pk>/finalizar/', views.FinalizarCirugiaView.as_view(), name='finalizar_cirugia'),

    path('doctores/', views.DoctoresView.as_view(), name='doctores'),
    path('doctores/plantilla/', views.PlantillaDoctoresView.as_view(), name='plantilla_doctores'),
    path('doctores/importar/', views.ImportarDoctoresView.as_view(), name='importar_doctores'),

    path('hospitales/', views.HospitalesView.as_view(), name='hospitales'),
    path('hospitales/plantilla/', views.PlantillaHospitalesView.as_view(), name='plantilla_hospitales'),
    path('hospitales/importar/', views.ImportarHospitalesView.as_view(), name='importar_hospitales'),
]
