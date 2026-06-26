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


def manifest(request):
    """Sirve el manifest.json desde la raíz."""
    manifest_path = os.path.join(settings.BASE_DIR, 'static', 'manifest.json')
    with open(manifest_path, 'r') as f:
        content = f.read()
    return HttpResponse(content, content_type='application/manifest+json')
