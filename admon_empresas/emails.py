import resend
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags


def _build_url(path, request=None):
    if request:
        return request.build_absolute_uri(path)
    return f"{settings.SITE_URL}{path}"


def url_registro_cliente(cliente):
    """Link de invitación que apunta al subdominio del cliente en producción
    (https://<slug>.ierp.mx/registro-cliente/<token>/) o a SITE_URL en dev."""
    base = (getattr(settings, 'BASE_DOMAIN', '') or '').strip()
    host = f"https://{cliente.slug_instancia}.{base}" if base else settings.SITE_URL
    return f"{host}/registro-cliente/{cliente.token_invitacion}/"


def enviar_invitacion_cliente(cliente):
    """Envía (o reenvía) el correo de invitación al cliente. Devuelve True/False."""
    import base64, os
    if not cliente.email_contacto:
        return False
    logo_url = ''
    try:
        path = os.path.join(settings.BASE_DIR, 'static', 'img', 'iErp_4k_sinfondo.png')
        with open(path, 'rb') as f:
            logo_url = f'data:image/png;base64,{base64.b64encode(f.read()).decode()}'
    except Exception:
        pass
    return send_html(
        subject=f"Bienvenido a iErp — Configura tu empresa: {cliente.nombre_comercial}",
        template='admon_empresas/emails/bienvenida_cliente.html',
        context={
            'nombre_comercial': cliente.nombre_comercial,
            'url_registro': url_registro_cliente(cliente),
            'logo_url': logo_url,
        },
        to=cliente.email_contacto,
    )


def send_plain(subject, text, to, attachments=None):
    """Correo de texto plano vía Resend (para avisos internos). Robusto: nunca lanza.
    `attachments`: lista opcional de {'filename': str, 'content': bytes}."""
    try:
        import base64
        resend.api_key = settings.RESEND_API_KEY
        html = '<pre style="font-family:monospace;font-size:12px;white-space:pre-wrap">' + \
               (text or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;') + '</pre>'
        payload = {
            'from': settings.DEFAULT_FROM_EMAIL,
            'to': [to] if isinstance(to, str) else list(to),
            'subject': subject,
            'html': html,
            'text': text,
        }
        if attachments:
            payload['attachments'] = [
                {'filename': a['filename'],
                 'content': base64.b64encode(a['content']).decode()}
                for a in attachments
            ]
        resend.Emails.send(payload)
        return True
    except Exception as e:
        print(f'[EMAIL PLAIN ERROR] {e}')
        return False


def send_html(subject, template, context, to, request=None, attachments=None):
    """Envía un correo HTML via Resend. Retorna True si fue exitoso.
    `attachments`: lista opcional de dicts {'filename': str, 'content': bytes}."""
    try:
        html_content = render_to_string(template, context)
        text_content = strip_tags(html_content)
        resend.api_key = settings.RESEND_API_KEY
        payload = {
            'from': settings.DEFAULT_FROM_EMAIL,
            'to': [to],
            'subject': subject,
            'html': html_content,
            'text': text_content,
        }
        if attachments:
            import base64
            payload['attachments'] = [
                {'filename': a['filename'],
                 'content': base64.b64encode(a['content']).decode()}
                for a in attachments
            ]
        resend.Emails.send(payload)
        return True
    except Exception as e:
        print(f'[EMAIL ERROR] {e}')
        return False
