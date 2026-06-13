import zoneinfo
from django.utils import timezone


class TimezoneMiddleware:
    """
    Activa la zona horaria del usuario detectada por el navegador.
    El cliente envía su timezone en la cookie 'tz' (ej. 'America/Mazatlan').
    Si no hay cookie, se usa America/Mexico_City como fallback para México.
    """
    FALLBACK_TZ = 'America/Mexico_City'

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tz_name = request.COOKIES.get('tz', self.FALLBACK_TZ)
        try:
            tz = zoneinfo.ZoneInfo(tz_name)
            timezone.activate(tz)
        except (zoneinfo.ZoneInfoNotFoundError, KeyError):
            timezone.activate(zoneinfo.ZoneInfo(self.FALLBACK_TZ))
        response = self.get_response(request)
        timezone.deactivate()
        return response
