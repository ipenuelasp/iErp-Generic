"""
URL configuration for iErp project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.views.static import serve as _media_serve
from . import views as core_views

urlpatterns = [
    path('sw.js', core_views.service_worker, name='service_worker'),
    path('manifest.json', core_views.manifest, name='manifest'),
    path('admin/', admin.site.urls),
    path('usuarios/', include('admon_usuarios.urls')),
    path('inventarios/', include('admon_inventarios.urls')),
    path('produccion/', include('admon_produccion.urls')),
    path('compras/', include('admon_compras.urls')),
    path('finanzas/', include('admon_finanzas.urls')),
    path('ventas/', include('admon_ventas.urls')),
    path('cirugias/', include('admon_cirugias.urls')),
    path('', include('admon_empresas.urls')),
    # Sirve archivos subidos (logos, isotipos, constancias) también en producción
    # (static() solo funciona con DEBUG=True; esta ruta funciona siempre).
    re_path(r'^media/(?P<path>.*)$', _media_serve, {'document_root': settings.MEDIA_ROOT}),
]
