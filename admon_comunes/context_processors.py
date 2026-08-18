def notificaciones(request):
    """No leídas + últimas para la campana del top bar, acotadas a la empresa
    activa (no se mezclan notificaciones entre empresas)."""
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return {'notif_no_leidas': 0, 'notif_lista': []}
    from django.db.models import Q
    from .models import Notificacion
    qs = Notificacion.objects.filter(usuario=request.user).select_related('actor')
    empresa = getattr(request, 'empresa', None)
    if empresa:
        qs = qs.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
    return {
        'notif_no_leidas': qs.filter(leida=False).count(),
        'notif_lista': list(qs[:12]),
    }
