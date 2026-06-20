"""
Catálogo de módulos del sistema (definido en código — un módulo nuevo
siempre trae código). La contratación por empresa y la asignación por
usuario viven en BD (modelos EmpresaModulo y AccesoModuloUsuario).
"""

# clave, nombre, icono FontAwesome, disponible (si ya tiene pantallas)
MODULOS = [
    {'clave': 'inventarios', 'nombre': 'Inventarios', 'icono': 'fa-boxes-stacked', 'disponible': True},
    {'clave': 'kits', 'nombre': 'Kits / Cajas', 'icono': 'fa-box', 'disponible': True},
    {'clave': 'produccion', 'nombre': 'Producción', 'icono': 'fa-industry', 'disponible': True},
    {'clave': 'compras', 'nombre': 'Compras', 'icono': 'fa-file-invoice-dollar', 'disponible': True},
    {'clave': 'finanzas', 'nombre': 'Finanzas', 'icono': 'fa-money-bill-wave', 'disponible': True},
    {'clave': 'ventas', 'nombre': 'Ventas', 'icono': 'fa-cash-register', 'disponible': True},
    {'clave': 'cirugias', 'nombre': 'Cirugías', 'icono': 'fa-syringe', 'disponible': True},
    {'clave': 'rrhh', 'nombre': 'Recursos Humanos', 'icono': 'fa-users', 'disponible': False},
]

MODULO_CHOICES = [(m['clave'], m['nombre']) for m in MODULOS]

# Módulos que ya tienen pantallas y se pueden contratar/usar hoy
MODULOS_DISPONIBLES = [m for m in MODULOS if m['disponible']]
CLAVES_DISPONIBLES = [m['clave'] for m in MODULOS_DISPONIBLES]


def modulo_de_resolver(resolver_match):
    """Determina a qué módulo pertenece la vista que se está resolviendo.
    Devuelve la clave del módulo o None si la ruta no pertenece a un módulo."""
    if not resolver_match:
        return None
    ns = resolver_match.namespace
    name = resolver_match.url_name or ''
    if ns == 'admon_inventarios':
        if name in ('kits', 'salidas_kit', 'salida_kit_detalle',
                    'cajas', 'armar_caja', 'reabastecer_caja'):
            return 'kits'
        return 'inventarios'
    return {
        'admon_compras': 'compras',
        'admon_finanzas': 'finanzas',
        'admon_produccion': 'produccion',
        'admon_ventas': 'ventas',
        'admon_cirugias': 'cirugias',
    }.get(ns)


def modulos_visibles(user, empresa):
    """Conjunto de claves de módulos que un usuario ve en una empresa.
    Regla: (contratados por la empresa) ∩ (asignados al usuario).
    Superuser y OWNER ven todo lo contratado."""
    if not empresa:
        return set()
    from .models import EmpresaModulo, AccesoModuloUsuario

    contratados = set(EmpresaModulo.objects.filter(
        empresa=empresa, activo=True).values_list('modulo', flat=True))

    perfil = getattr(user, 'perfil', None)
    if user.is_superuser or (perfil and perfil.tipo_usuario == 'OWNER'):
        return contratados

    asignados = set(AccesoModuloUsuario.objects.filter(
        usuario=user, empresa=empresa).values_list('modulo', flat=True))
    return contratados & asignados
