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


# ---------------------------------------------------------------------------
# Secciones (pantallas/ligas dentro de cada módulo). Permiso fino por usuario:
# por defecto el usuario ve TODAS las secciones de sus módulos; se le pueden
# OCULTAR algunas (blocklist por usuario). OWNER/superuser ven todo.
# Cada sección lista los url_name que cubre (para el bloqueo en middleware).
# ---------------------------------------------------------------------------
SECCIONES = [
    # Ventas
    {'clave': 'ventas.cotizaciones', 'nombre': 'Cotizaciones', 'modulo': 'ventas',
     'urls': ['historial_cotizaciones', 'nueva_cotizacion', 'editar_cotizacion', 'cotizacion_detalle']},
    {'clave': 'ventas.pedidos', 'nombre': 'Pedidos de Venta', 'modulo': 'ventas',
     'urls': ['historial_pedidos', 'nuevo_pedido', 'editar_pedido', 'pedido_detalle', 'entrega_pedido', 'pedido_pdf']},
    {'clave': 'ventas.cirugias_facturar', 'nombre': 'Cirugías por Facturar', 'modulo': 'ventas',
     'urls': ['cirugias_por_facturar', 'generar_pedido_cirugia']},
    {'clave': 'ventas.liquidaciones', 'nombre': 'Liquidar Salidas', 'modulo': 'ventas',
     'urls': ['liquidaciones', 'liquidar_salida']},
    {'clave': 'ventas.clientes', 'nombre': 'Clientes', 'modulo': 'ventas', 'urls': ['clientes']},
    # Compras
    {'clave': 'compras.ordenes', 'nombre': 'Órdenes de Compra', 'modulo': 'compras',
     'urls': ['historial_ordenes', 'nueva_orden', 'orden_form', 'orden_detalle', 'recepcion_oc', 'importar_amazon', 'orden_pdf']},
    {'clave': 'compras.proveedores', 'nombre': 'Proveedores', 'modulo': 'compras', 'urls': ['proveedores']},
    {'clave': 'compras.autorizadores', 'nombre': 'Cadena de Autorización', 'modulo': 'compras', 'urls': ['autorizadores']},
    # Finanzas
    {'clave': 'finanzas.por_pagar', 'nombre': 'Cuentas por Pagar', 'modulo': 'finanzas',
     'urls': ['cuentas_por_pagar', 'factura_detalle', 'registrar_factura']},
    {'clave': 'finanzas.por_cobrar', 'nombre': 'Cuentas por Cobrar', 'modulo': 'finanzas',
     'urls': ['cuentas_por_cobrar', 'factura_cliente_detalle', 'registrar_cobro', 'facturar_xlsx']},
    {'clave': 'finanzas.estados_cuenta', 'nombre': 'Estados de Cuenta', 'modulo': 'finanzas',
     'urls': ['estados_cuenta', 'estado_cuenta_cliente']},
    {'clave': 'finanzas.pagos', 'nombre': 'Pagos', 'modulo': 'finanzas',
     'urls': ['historial_pagos', 'registrar_pago', 'adjuntar_complemento', 'pago_pdf']},
    {'clave': 'finanzas.gastos', 'nombre': 'Gastos', 'modulo': 'finanzas', 'urls': ['gastos']},
    {'clave': 'finanzas.otros', 'nombre': 'Otros e Impuestos', 'modulo': 'finanzas', 'urls': ['otros_resultados']},
    {'clave': 'finanzas.conciliacion', 'nombre': 'Conciliación SAT', 'modulo': 'finanzas', 'urls': ['conciliacion_sat']},
    {'clave': 'finanzas.estado_resultados', 'nombre': 'Estado de Resultados', 'modulo': 'finanzas', 'urls': ['estado_resultados']},
    # Inventarios
    {'clave': 'inventarios.catalogos', 'nombre': 'Catálogos', 'modulo': 'inventarios', 'urls': ['catalogos_productos']},
    {'clave': 'inventarios.recepciones', 'nombre': 'Recepciones', 'modulo': 'inventarios',
     'urls': ['recepciones', 'nueva_recepcion', 'recepcion_directa']},
    {'clave': 'inventarios.existencias', 'nombre': 'Existencias', 'modulo': 'inventarios', 'urls': ['existencias']},
    {'clave': 'inventarios.kardex', 'nombre': 'Kardex', 'modulo': 'inventarios', 'urls': ['kardex']},
    {'clave': 'inventarios.traspasos', 'nombre': 'Traspasos', 'modulo': 'inventarios', 'urls': ['traspasos', 'traspaso_detalle']},
    # Kits / Cajas
    {'clave': 'kits.cajas', 'nombre': 'Armar Cajas', 'modulo': 'kits', 'urls': ['cajas', 'armar_caja', 'reabastecer_caja']},
    {'clave': 'kits.plantillas', 'nombre': 'Plantillas Kit', 'modulo': 'kits', 'urls': ['kits']},
    {'clave': 'kits.salidas', 'nombre': 'Salidas de Caja', 'modulo': 'kits', 'urls': ['salidas_kit', 'salida_kit_detalle']},
    # Cirugías
    {'clave': 'cirugias.solicitudes', 'nombre': 'Solicitudes', 'modulo': 'cirugias', 'urls': ['solicitudes', 'solicitud_detalle']},
    {'clave': 'cirugias.doctores', 'nombre': 'Doctores', 'modulo': 'cirugias', 'urls': ['doctores']},
    {'clave': 'cirugias.hospitales', 'nombre': 'Hospitales', 'modulo': 'cirugias', 'urls': ['hospitales']},
    # Producción
    {'clave': 'produccion.recetas', 'nombre': 'Recetas', 'modulo': 'produccion', 'urls': ['recetas']},
    {'clave': 'produccion.ordenes', 'nombre': 'Órdenes de Producción', 'modulo': 'produccion',
     'urls': ['ordenes_produccion', 'orden_produccion_detalle']},
]

# Índice url_name -> clave de sección (para el bloqueo en middleware)
_URL_A_SECCION = {u: s['clave'] for s in SECCIONES for u in s['urls']}


def secciones_de_modulo(modulo):
    return [s for s in SECCIONES if s['modulo'] == modulo]


def seccion_de_resolver(resolver_match):
    """Clave de la sección a la que pertenece la vista actual (o None)."""
    if not resolver_match:
        return None
    return _URL_A_SECCION.get(resolver_match.url_name or '')


def secciones_ocultas(user, empresa):
    """Claves de sección OCULTAS para el usuario (blocklist). OWNER/superuser: ninguna."""
    if not empresa or not getattr(user, 'is_authenticated', False):
        return set()
    perfil = getattr(user, 'perfil', None)
    if user.is_superuser or (perfil and perfil.tipo_usuario == 'OWNER'):
        return set()
    from .models import SeccionOcultaUsuario
    return set(SeccionOcultaUsuario.objects.filter(
        usuario=user, empresa=empresa).values_list('seccion', flat=True))


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
