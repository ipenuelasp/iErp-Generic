"""
Motor de autorización de órdenes de compra por cadena de supervisión.

Reglas:
- Cada usuario tiene un AutorizadorCompra con monto_autorizado (0 = sin límite)
  y un supervisor.
- Al solicitar autorización, si el creador cubre el monto, la OC queda autorizada.
  Si no, escala a su supervisor.
- Cada eslabón que recibe la OC debe firmar (aprobar/rechazar). Si aprueba pero su
  límite no cubre el total, su firma queda registrada y la OC sube a su supervisor.
- La OC queda AUTORIZADA cuando firma quien sí cubre el monto (o llega a la cima
  de la cadena: alguien sin supervisor).
"""
from django.utils import timezone

from .models import AutorizadorCompra, AutorizacionOC


class ErrorAutorizacion(Exception):
    pass


def _config(empresa, usuario):
    return AutorizadorCompra.objects.filter(
        empresa=empresa, usuario=usuario, activo=True).first()


def solicitar_autorizacion(orden, solicitante):
    """Envía la OC al circuito de autorización. Devuelve la OC actualizada."""
    if orden.estado not in ('BORRADOR', 'RECHAZADO'):
        raise ErrorAutorizacion("Solo se pueden enviar borradores a autorización.")
    if not orden.detalles.exists():
        raise ErrorAutorizacion("La orden no tiene partidas.")

    cfg = _config(orden.empresa, solicitante)
    if not cfg:
        raise ErrorAutorizacion(
            "No tienes un perfil de autorización de compras configurado. "
            "Pide a la matriz que defina tu límite y supervisor.")

    orden.motivo_rechazo = None
    orden.fecha_solicitud = timezone.now()

    # El propio comprador cubre el monto → autorizada de inmediato
    if cfg.cubre(orden.total):
        AutorizacionOC.objects.create(
            orden=orden, usuario=solicitante, secuencia=1,
            accion='APROBADO', es_final=True,
            comentario="Auto-autorizada (dentro de su límite).")
        orden.estado = 'AUTORIZADO'
        orden.autorizador_actual = None
        orden.fecha_autorizacion = timezone.now()
        orden.save()
        return orden

    # Escala al supervisor
    if not cfg.supervisor:
        raise ErrorAutorizacion(
            "El monto supera tu límite y no tienes supervisor configurado. "
            "No hay quién autorice esta orden.")

    orden.estado = 'SOLICITADO'
    orden.autorizador_actual = cfg.supervisor
    orden.save()
    return orden


def aprobar(orden, usuario, comentario=None):
    """Registra la firma de aprobación del autorizador actual y decide si
    la OC queda autorizada o sigue escalando."""
    if orden.estado != 'SOLICITADO':
        raise ErrorAutorizacion("La orden no está en proceso de autorización.")
    if orden.autorizador_actual_id != usuario.id:
        raise ErrorAutorizacion("No te corresponde autorizar esta orden.")

    secuencia = orden.autorizaciones.count() + 1
    cfg = _config(orden.empresa, usuario)

    # Cubre el monto, o es la cima de la cadena (sin supervisor) → cierra
    cubre = cfg.cubre(orden.total) if cfg else False
    sin_superior = (not cfg) or (not cfg.supervisor)

    if cubre or sin_superior:
        AutorizacionOC.objects.create(
            orden=orden, usuario=usuario, secuencia=secuencia,
            accion='APROBADO', es_final=True, comentario=comentario)
        orden.estado = 'AUTORIZADO'
        orden.autorizador_actual = None
        orden.fecha_autorizacion = timezone.now()
        orden.save()
        return orden

    # Firma y escala al siguiente supervisor
    AutorizacionOC.objects.create(
        orden=orden, usuario=usuario, secuencia=secuencia,
        accion='APROBADO', es_final=False,
        comentario=comentario or "Revisado, escala por monto.")
    orden.autorizador_actual = cfg.supervisor
    orden.save()
    return orden


def rechazar(orden, usuario, motivo):
    if orden.estado != 'SOLICITADO':
        raise ErrorAutorizacion("La orden no está en proceso de autorización.")
    if orden.autorizador_actual_id != usuario.id:
        raise ErrorAutorizacion("No te corresponde autorizar esta orden.")
    if not motivo:
        raise ErrorAutorizacion("El motivo de rechazo es obligatorio.")

    secuencia = orden.autorizaciones.count() + 1
    AutorizacionOC.objects.create(
        orden=orden, usuario=usuario, secuencia=secuencia,
        accion='RECHAZADO', es_final=True, comentario=motivo)
    orden.estado = 'RECHAZADO'
    orden.autorizador_actual = None
    orden.motivo_rechazo = motivo
    orden.save()
    return orden


def previsualizar_cadena(empresa, solicitante, total):
    """Devuelve la lista de firmantes que recolectaría una OC de este monto,
    para mostrarla antes de enviar. No persiste nada."""
    cadena = []
    visto = set()
    cfg = _config(empresa, solicitante)
    while cfg and cfg.usuario_id not in visto:
        visto.add(cfg.usuario_id)
        cubre = cfg.cubre(total)
        cadena.append({
            'usuario': cfg.usuario,
            'limite': cfg.monto_autorizado,
            'sin_limite': cfg.sin_limite,
            'cubre': cubre,
        })
        if cubre or not cfg.supervisor:
            break
        cfg = _config(empresa, cfg.supervisor)
    return cadena
