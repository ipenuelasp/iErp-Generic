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
    path('por-cobrar/facturar-xlsx/', views.ExcelFacturacionView.as_view(), name='facturar_xlsx'),
    path('cxc/<int:pk>/', views.FacturaClienteDetalleView.as_view(), name='factura_cliente_detalle'),
    path('cxc/<int:pk>/pdf/', views.FacturaPDFView.as_view(), name='factura_cliente_pdf'),
    path('estados-cuenta/', views.EstadosCuentaView.as_view(), name='estados_cuenta'),
    path('estado-cuenta/<int:cliente_id>/', views.EstadoCuentaClientePDFView.as_view(), name='estado_cuenta_cliente'),
    path('cobros/nuevo/', views.RegistrarCobroView.as_view(), name='registrar_cobro'),

    # Gastos de operación
    path('gastos/', views.GastosView.as_view(), name='gastos'),
    path('otros-resultados/', views.OtrosResultadosView.as_view(), name='otros_resultados'),
    path('conciliacion-sat/', views.ConciliacionSATView.as_view(), name='conciliacion_sat'),

    # Reportes
    path('estado-resultados/', views.EstadoResultadosView.as_view(), name='estado_resultados'),
]
