from django.urls import path
from . import views

app_name = 'admon_produccion'

urlpatterns = [
    path('recetas/', views.RecetasView.as_view(), name='recetas'),
    path('ordenes/', views.OrdenesProduccionView.as_view(), name='ordenes_produccion'),
    path('ordenes/<int:pk>/', views.OrdenProduccionDetalleView.as_view(), name='orden_produccion_detalle'),
]
