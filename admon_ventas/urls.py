from django.urls import path
from . import views

app_name = 'admon_ventas'

urlpatterns = [
    path('clientes/', views.ClientesView.as_view(), name='clientes'),
    path('clientes/plantilla/', views.DescargarPlantillaClientesView.as_view(), name='plantilla_clientes'),
    path('clientes/importar/', views.ImportarClientesView.as_view(), name='importar_clientes'),
    path('clientes/leer-csf/', views.LeerConstanciaView.as_view(), name='leer_csf'),

    path('pedidos/', views.HistorialPedidosView.as_view(), name='historial_pedidos'),
    path('pedidos/nuevo/', views.NuevoPedidoView.as_view(), name='nuevo_pedido'),
    path('pedidos/<int:pk>/', views.PedidoDetalleView.as_view(), name='pedido_detalle'),
    path('pedidos/<int:pk>/editar/', views.EditarPedidoView.as_view(), name='editar_pedido'),
    path('pedidos/<int:pk>/entregar/', views.EntregaPedidoView.as_view(), name='entrega_pedido'),
    path('pedidos/<int:pk>/pdf/', views.PedidoPDFView.as_view(), name='pedido_pdf'),

    path('cotizaciones/', views.HistorialCotizacionesView.as_view(), name='historial_cotizaciones'),
    path('cotizaciones/nueva/', views.NuevaCotizacionView.as_view(), name='nueva_cotizacion'),
    path('cotizaciones/<int:pk>/', views.CotizacionDetalleView.as_view(), name='cotizacion_detalle'),
    path('cotizaciones/<int:pk>/editar/', views.EditarCotizacionView.as_view(), name='editar_cotizacion'),
    path('cotizaciones/<int:pk>/pdf/', views.CotizacionPDFView.as_view(), name='cotizacion_pdf'),

    path('cirugias-por-facturar/', views.CirugiasPorFacturarView.as_view(), name='cirugias_por_facturar'),
    path('cirugias-por-facturar/<int:pk>/generar/', views.GenerarPedidoCirugiaView.as_view(), name='generar_pedido_cirugia'),

    path('liquidaciones/', views.LiquidacionesView.as_view(), name='liquidaciones'),
    path('liquidaciones/<int:salida_id>/', views.LiquidarSalidaView.as_view(), name='liquidar_salida'),
]
