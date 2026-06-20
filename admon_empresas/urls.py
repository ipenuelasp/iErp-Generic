from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('configuracion/', views.ConfiguracionView.as_view(), name='configuracion'),
    path('registro-cliente/<uuid:token>/', views.registro_cliente_view, name='registro_cliente'),
    path('login/', views.CustomLoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('', views.home_view, name='home'), # La página del logo
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'), # Los indicadores
    path('dashboard-ejecutivo/', views.dashboard_ejecutivo_view, name='dashboard_ejecutivo'),
    path('cambiar-sucursal/<int:sucursal_id>/', views.cambiar_contexto, name='cambiar_contexto'),
    path('cambiar-empresa/<int:empresa_id>/', views.cambiar_empresa, name='cambiar_empresa'),

    path('clientes/', views.lista_clientes, name='lista_clientes'),
    path('clientes/nuevo/', views.crear_cliente, name='crear_cliente'),
    path('clientes/<int:pk>/editar/', views.editar_cliente, name='editar_cliente'),
    path('clientes/<int:pk>/eliminar/', views.eliminar_cliente, name='eliminar_cliente'),
    path('clientes/<int:cliente_pk>/empresa/nueva/', views.crear_empresa, name='crear_empresa'),
    path('clientes/empresa/<int:empresa_pk>/sucursal/nueva/', views.crear_sucursal_cliente, name='crear_sucursal_cliente'),
    path('clientes/sucursal/<int:pk>/editar/', views.editar_sucursal_cliente, name='editar_sucursal_cliente'),
    path('clientes/sucursal/<int:pk>/eliminar/', views.eliminar_sucursal_cliente, name='eliminar_sucursal_cliente'),
    path('clientes/empresa/<int:pk>/eliminar/', views.eliminar_empresa, name='eliminar_empresa'),

    path('configuracion/sucursal/editar/<int:pk>/', views.editar_sucursal, name='editar_sucursal'),
    path('configuracion/sucursal/eliminar/<int:pk>/', views.eliminar_sucursal, name='eliminar_sucursal'),
    path('configuracion/moneda/editar/<int:pk>/', views.editar_moneda, name='editar_moneda'),
    path('configuracion/moneda/eliminar/<int:pk>/', views.eliminar_moneda, name='eliminar_moneda'),
    path('configuracion/impuesto/editar/<int:pk>/', views.editar_impuesto, name='editar_impuesto'),
]
