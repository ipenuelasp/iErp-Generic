from django.urls import path
from . import views, views_traspasos, views_kits, views_cajas

app_name = 'admon_inventarios'

urlpatterns = [
    # Catálogos y stock
    path('catalogos/', views.CatalogoProductosView.as_view(), name='catalogos_productos'),
    path('productos/plantilla/', views.DescargarPlantillaProductosView.as_view(), name='plantilla_productos'),
    path('productos/importar/', views.ImportarProductosView.as_view(), name='importar_productos'),
    path('recepciones/', views.RecepcionesView.as_view(), name='recepciones'),
    path('recepciones/nueva/', views.NuevaRecepcionDirectaView.as_view(), name='nueva_recepcion'),
    path('existencias/', views.ExistenciasView.as_view(), name='existencias'),
    path('kardex/', views.KardexView.as_view(), name='kardex'),

    # Traspasos entre sucursales
    path('traspasos/', views_traspasos.TraspasosView.as_view(), name='traspasos'),
    path('traspasos/<int:pk>/', views_traspasos.TraspasoDetalleView.as_view(), name='traspaso_detalle'),

    # Cajas (armado libre + consigna)
    path('cajas/', views_cajas.CajasView.as_view(), name='cajas'),
    path('cajas/<int:pk>/armar/', views_cajas.ArmarCajaView.as_view(), name='armar_caja'),

    # Kits / cajas quirúrgicas
    path('kits/', views_kits.KitsView.as_view(), name='kits'),
    path('kits/plantilla/', views.DescargarPlantillaKitsView.as_view(), name='plantilla_kits'),
    path('kits/importar/', views.ImportarKitsView.as_view(), name='importar_kits'),
    path('kits/cajas/<int:pk>/reabastecer/', views_kits.ReabastecerCajaView.as_view(), name='reabastecer_caja'),
    path('kits/salidas/', views_kits.SalidasKitView.as_view(), name='salidas_kit'),
    path('kits/salidas/<int:pk>/', views_kits.SalidaKitDetalleView.as_view(), name='salida_kit_detalle'),
    path('kits/salidas/<int:pk>/vale/', views_kits.ValeSalidaPDFView.as_view(), name='vale_salida_pdf'),
    path('kits/salidas/<int:pk>/consumo/', views_kits.HojaConsumoPDFView.as_view(), name='hoja_consumo_pdf'),
]
