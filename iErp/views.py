from django.http import HttpResponse
from django.conf import settings
import os


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
