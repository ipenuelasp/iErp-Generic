from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.http import JsonResponse

from .models import Notificacion


@login_required
def abrir_notificacion(request, pk):
    """Marca la notificación como leída y redirige a su destino."""
    n = get_object_or_404(Notificacion, pk=pk, usuario=request.user)
    if not n.leida:
        n.leida = True
        n.leida_en = timezone.now()
        n.save(update_fields=['leida', 'leida_en'])
    return redirect(n.url or 'home')


@login_required
def marcar_todas_leidas(request):
    """Marca todas las del usuario como leídas."""
    Notificacion.objects.filter(usuario=request.user, leida=False).update(
        leida=True, leida_en=timezone.now())
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'ok': True})
    return redirect(request.META.get('HTTP_REFERER') or 'home')
