from django.urls import path
from . import views

app_name = 'admon_finanzas'

urlpatterns = [
    path('por-pagar/', views.CuentasPorPagarView.as_view(), name='cuentas_por_pagar'),
    path('facturas/<int:pk>/', views.FacturaDetalleView.as_view(), name='factura_detalle'),
    path('ordenes/<int:oc_id>/facturar/', views.RegistrarFacturaView.as_view(), name='registrar_factura'),
    path('pagos/', views.HistorialPagosView.as_view(), name='historial_pagos'),
    path('pagos/nuevo/', views.RegistrarPagoView.as_view(), name='registrar_pago'),
    path('pagos/<int:pk>/complemento/', views.AdjuntarComplementoView.as_view(), name='adjuntar_complemento'),
    path('pagos/<int:pk>/pdf/', views.PagoPDFView.as_view(), name='pago_pdf'),

    # Cuentas por cobrar (clientes)
    path('por-cobrar/', views.CuentasPorCobrarView.as_view(), name='cuentas_por_cobrar'),
    path('cxc/<int:pk>/', views.FacturaClienteDetalleView.as_view(), name='factura_cliente_detalle'),
    path('estado-cuenta/<int:cliente_id>/', views.EstadoCuentaClientePDFView.as_view(), name='estado_cuenta_cliente'),
    path('cobros/nuevo/', views.RegistrarCobroView.as_view(), name='registrar_cobro'),

    # Gastos de operación
    path('gastos/', views.GastosView.as_view(), name='gastos'),

    # Reportes
    path('estado-resultados/', views.EstadoResultadosView.as_view(), name='estado_resultados'),
]
