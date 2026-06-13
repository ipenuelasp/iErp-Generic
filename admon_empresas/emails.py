import resend
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags


def _build_url(path, request=None):
    if request:
        return request.build_absolute_uri(path)
    return f"{settings.SITE_URL}{path}"


def send_html(subject, template, context, to, request=None):
    """Envía un correo HTML via Resend. Retorna True si fue exitoso."""
    try:
        html_content = render_to_string(template, context)
        text_content = strip_tags(html_content)
        resend.api_key = settings.RESEND_API_KEY
        resend.Emails.send({
            'from': settings.DEFAULT_FROM_EMAIL,
            'to': [to],
            'subject': subject,
            'html': html_content,
            'text': text_content,
        })
        return True
    except Exception as e:
        print(f'[EMAIL ERROR] {e}')
        return False
