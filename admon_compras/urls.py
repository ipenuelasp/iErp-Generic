from django.urls import path
from . import views, views_recepcion

app_name = 'admon_compras'

urlpatterns = [
    path('proveedores/', views.ProveedoresView.as_view(), name='proveedores'),
    path('proveedores/plantilla/', views.DescargarPlantillaProveedoresView.as_view(), name='plantilla_proveedores'),
    path('proveedores/importar/', views.ImportarProveedoresView.as_view(), name='importar_proveedores'),
    path('autorizadores/', views.AutorizadoresView.as_view(), name='autorizadores'),

    path('ordenes/', views.HistorialOrdenesView.as_view(), name='historial_ordenes'),
    path('ordenes/importar-amazon/', views.ImportarAmazonView.as_view(), name='importar_amazon'),
    path('ordenes/importar-amazon/previsualizar/', views.PrevisualizarAmazonView.as_view(), name='previsualizar_amazon'),
    path('ordenes/nueva/', views.NuevaOrdenView.as_view(), name='nueva_orden'),
    path('ordenes/<int:pk>/', views.OrdenDetalleView.as_view(), name='orden_detalle'),
    path('ordenes/<int:pk>/editar/', views.EditarOrdenView.as_view(), name='editar_orden'),
    path('ordenes/<int:pk>/pdf/', views.OrdenPDFView.as_view(), name='orden_pdf'),
    path('ordenes/<int:pk>/recibir/', views_recepcion.RecepcionOCView.as_view(), name='recepcion_oc'),
]
