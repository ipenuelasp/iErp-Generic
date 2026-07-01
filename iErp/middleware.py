import traceback
import zoneinfo
from django.conf import settings
from django.http import Http404
from django.core.exceptions import PermissionDenied
from django.utils import timezone


class ErrorNotifyMiddleware:
    """Avisa por correo cuando una vista truena (error 500), con el contexto útil:
    empresa/cliente, usuario, URL, método, datos enviados y la traza."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        # 404 y 403 no son fallas del sistema
        if isinstance(exception, (Http404, PermissionDenied)):
            return None
        destino = getattr(settings, 'ERROR_NOTIFY_EMAIL', '') or ''
        if not destino:
            return None
        try:
            from admon_empresas.emails import send_plain

            empresa = getattr(request, 'empresa', None)
            empresa_txt = getattr(empresa, 'nombre_fiscal', None) or '—'
            user = getattr(request, 'user', None)
            usuario = getattr(user, 'username', None) or 'anónimo'
            try:
                url = request.build_absolute_uri()
            except Exception:
                url = request.path
            try:
                host = request.get_host()
            except Exception:
                host = request.META.get('HTTP_HOST', '—')

            # Datos enviados (sin csrf ni contraseñas), recortados
            datos = []
            if request.method == 'POST':
                for k in request.POST:
                    if k == 'csrfmiddlewaretoken' or 'pass' in k.lower():
                        continue
                    v = ', '.join(request.POST.getlist(k))
                    datos.append(f"  {k} = {v[:200]}")
            datos_txt = '\n'.join(datos) or '  (sin datos POST)'

            ahora = timezone.now()
            sede = request.session.get('sucursal_nombre', '—')
            traza = traceback.format_exc()

            # Resumen (cuerpo del correo)
            resumen = (
                f"Ocurrió un error en iErp. El detalle completo va en el adjunto.\n\n"
                f"Fecha:    {ahora:%d/%m/%Y %H:%M:%S}\n"
                f"Empresa:  {empresa_txt}\n"
                f"Sede:     {sede}\n"
                f"Usuario:  {usuario}\n"
                f"Host:     {host}\n"
                f"Método:   {request.method}\n"
                f"URL:      {url}\n"
                f"Error:    {type(exception).__name__}: {exception}\n"
            )
            # Detalle completo (adjunto .txt)
            detalle = (
                f"iErp — Reporte de error\n{'='*60}\n"
                f"{resumen}\n"
                f"--- Datos enviados (POST) ---\n{datos_txt}\n\n"
                f"--- Traza completa ---\n{traza}"
            )
            nombre = f"error_{ahora:%Y%m%d_%H%M%S}.txt"
            send_plain(
                f"[iErp] Error · {empresa_txt} · {request.path}", resumen, destino,
                attachments=[{'filename': nombre, 'content': detalle.encode('utf-8')}])
        except Exception as e:
            print(f'[ERROR NOTIFY] {e}')
        return None  # deja que Django siga con su handler500 (página amigable)


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
