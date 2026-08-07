def notificaciones(request):
    """No leídas + últimas para la campana del top bar."""
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return {'notif_no_leidas': 0, 'notif_lista': []}
    from .models import Notificacion
    qs = Notificacion.objects.filter(usuario=request.user).select_related('actor')
    return {
        'notif_no_leidas': qs.filter(leida=False).count(),
        'notif_lista': list(qs[:12]),
    }
