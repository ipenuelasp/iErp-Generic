from django.http import HttpResponse
from django.conf import settings
from django.template.loader import render_to_string
import os


def _tema_de(request):
    """Tema de página de error de la empresa activa (default 'robot')."""
    empresa = getattr(request, 'empresa', None)
    return getattr(empresa, 'tema_error', None) or 'robot'


def _render_error(request, *, codigo, titulo, mensaje, reintentar=False):
    # render_to_string sin 'request' evita context processors (que tocan BD),
    # importante sobre todo en el handler 500.
    html = render_to_string('errores/pagina_error.html', {
        'codigo': codigo, 'titulo': titulo, 'mensaje': mensaje,
        'reintentar': reintentar, 'tema': _tema_de(request),
        'marca': 'iErp · Sistema de Gestión',
    })
    return HttpResponse(html, status=codigo)


def error_400(request, exception=None):
    return _render_error(request, codigo=400, titulo='Solicitud incorrecta',
                         mensaje='Algo en la solicitud no se entendió. Vuelve a intentarlo.')


def error_403(request, exception=None):
    return _render_error(request, codigo=403, titulo='Sin acceso',
                         mensaje='No tienes permiso para ver esta página.<br>Si crees que es un error, contacta a tu administrador.')


def error_404(request, exception=None):
    return _render_error(request, codigo=404, titulo='Página no encontrada',
                         mensaje='La página que buscas no existe o cambió de lugar.')


def error_500(request):
    return _render_error(request, codigo=500, titulo='Algo salió mal',
                         mensaje='Tuvimos un problema procesando tu solicitud.<br>Ya estamos en ello, intenta de nuevo en un momento.',
                         reintentar=True)


def service_worker(request):
    """Sirve el service worker desde la raíz para que tenga scope global."""
    sw_path = os.path.join(settings.BASE_DIR, 'static', 'sw.js')
    with open(sw_path, 'r') as f:
        content = f.read()
    return HttpResponse(content, content_type='application/javascript')


def _empresa_para_pwa(request):
    """Empresa que define la marca del PWA: la activa, o la del subdominio
    (tenant) aunque no haya sesión (para el prompt de instalar en el login)."""
    empresa = getattr(request, 'empresa', None)
    if empresa:
        return empresa
    tenant = getattr(request, 'tenant', None)
    if tenant:
        from admon_empresas.models import Empresa
        return (Empresa.objects.filter(cliente=tenant).exclude(isotipo='')
                .exclude(isotipo__isnull=True).first()
                or Empresa.objects.filter(cliente=tenant).first())
    return None


_ICONOS_IERP = [
    {"src": f"/static/img/icons/icon-{s}x{s}.png", "sizes": f"{s}x{s}", "type": "image/png",
     **({"purpose": "any maskable"} if s in (192, 512) else {})}
    for s in (72, 96, 128, 144, 152, 192, 384, 512)
]


def manifest(request):
    """Manifest PWA dinámico: usa el isotipo de la empresa (activa o del
    subdominio) como ícono e identidad; si no tiene, cae al ícono de iErp."""
    from django.http import JsonResponse
    empresa = _empresa_para_pwa(request)
    nombre = empresa.nombre_fiscal if empresa else 'iErp'
    if empresa and empresa.isotipo:
        u = empresa.isotipo.url
        icons = [{"src": u, "sizes": "192x192"}, {"src": u, "sizes": "512x512"}]
    else:
        icons = _ICONOS_IERP
    data = {
        "name": nombre,
        "short_name": (nombre[:12] if empresa else 'iErp'),
        "description": "iErp: ERP multiempresa (inventarios, ventas, compras, finanzas, tareas y más).",
        "start_url": "/tareas/movil/?pwa=1",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait-primary",
        "theme_color": "#1e2d4f",
        "background_color": "#1e2d4f",
        "lang": "es-MX",
        "icons": icons,
        "shortcuts": [
            {"name": "Mis tareas", "short_name": "Mis tareas", "url": "/tareas/movil/?pwa=1"},
            {"name": "Tableros (escritorio)", "short_name": "Tableros", "url": "/tareas/"},
        ],
    }
    return JsonResponse(data, content_type='application/manifest+json')
