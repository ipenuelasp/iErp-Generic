def resolver_tenant(request):
    """Devuelve el ClienteSaaS según el subdominio (<slug>.ierp.mx), o None
    en desarrollo / dominio raíz / portal del proveedor (www, admin, app)."""
    from django.conf import settings
    base = getattr(settings, 'BASE_DOMAIN', '') or ''
    if not base:
        return None  # dev: sin scoping por subdominio
    host = request.get_host().split(':')[0].lower()
    if host == base or not host.endswith('.' + base):
        return None  # dominio raíz / host no-tenant
    sub = host[:-(len(base) + 1)]
    if sub in ('', 'www', 'admin', 'app'):
        return None  # portal del proveedor (superadmin)
    from .models import ClienteSaaS
    return ClienteSaaS.objects.filter(slug_instancia=sub).first()


def es_portal_proveedor(request):
    """True si el host es el portal del PROVEEDOR: el dominio raíz (ierp.mx) o
    www/admin/app. Ahí solo opera el superadmin; un usuario de cliente debe
    entrar por el subdominio de su empresa. En desarrollo (sin BASE_DOMAIN) y en
    los subdominios de cliente devuelve False."""
    from django.conf import settings
    base = (getattr(settings, 'BASE_DOMAIN', '') or '').lower()
    if not base:
        return False  # dev
    host = request.get_host().split(':')[0].lower()
    if host == base:
        return True
    if host.endswith('.' + base):
        sub = host[:-(len(base) + 1)]
        return sub in ('www', 'admin', 'app')
    return False


def _subdominio_de_usuario(user):
    """Slug de la instancia (subdominio) del cliente al que pertenece el usuario,
    tomando su empresa por defecto (o la primera). None si no tiene empresa."""
    perfil = getattr(user, 'perfil', None)
    if not perfil:
        return None
    emp = getattr(perfil, 'empresa_default', None) or perfil.empresas.first()
    return emp.cliente.slug_instancia if emp and emp.cliente_id else None


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Inicializamos con valores por defecto para evitar el error de "no attribute"
        request.empresa = None
        request.empresas = []
        request.sucursal_activa = None

        # Tenant del subdominio (None = dev / portal proveedor)
        request.tenant = resolver_tenant(request)

        if request.user.is_authenticated:
            # El dominio raíz (ierp.mx) y www/admin/app son el portal del PROVEEDOR:
            # solo el superadmin opera ahí. Un usuario de cliente no puede usar la
            # app en el raíz; se cierra su sesión y se le manda al login con el
            # aviso de que entre por el subdominio de su empresa.
            if es_portal_proveedor(request) and not request.user.is_superuser:
                from django.conf import settings
                from django.contrib.auth import logout
                from django.contrib import messages
                from django.shortcuts import redirect
                slug = _subdominio_de_usuario(request.user)
                base = (getattr(settings, 'BASE_DOMAIN', '') or '').lower()
                logout(request)
                if slug and base:
                    messages.info(request, "Este portal es solo administrativo. "
                                  f"Ingresa a tu empresa en {slug}.{base}")
                else:
                    messages.info(request, "Este portal es solo administrativo. "
                                  "Ingresa desde el subdominio de tu empresa.")
                return redirect('login')

            perfil = getattr(request.user, 'perfil', None)

            if perfil:
                # 1. Empresas permitidas, ACOTADAS al tenant del subdominio
                empresas_qs = perfil.empresas.all()
                if request.tenant:
                    empresas_qs = empresas_qs.filter(cliente=request.tenant)
                request.empresas = empresas_qs

                # 2. Candado: en un portal de cliente, si el usuario (no superadmin)
                #    no tiene empresas de ese tenant, no pertenece aquí.
                if request.tenant and not request.user.is_superuser and not empresas_qs.exists():
                    from django.contrib.auth import logout
                    from django.contrib import messages
                    from django.shortcuts import redirect
                    logout(request)
                    messages.error(request, "Tu cuenta no pertenece a este portal.")
                    return redirect('login')

                # 3. Empresa activa (siempre dentro del conjunto permitido/acotado)
                empresa_id = request.session.get('empresa_id')
                empresa = empresas_qs.filter(id=int(empresa_id)).first() if empresa_id else None
                if not empresa:
                    dflt = getattr(perfil, 'empresa_default', None)
                    empresa = (empresas_qs.filter(id=dflt.id).first() if dflt else None) or empresas_qs.first()
                if empresa:
                    request.session['empresa_id'] = empresa.id
                request.empresa = empresa

                # 4. Sucursal Activa
                sucursal_id = request.session.get('sucursal_id')
                if sucursal_id and empresa:
                    from .models import Sucursal
                    request.sucursal_activa = Sucursal.objects.filter(id=sucursal_id, empresa=empresa).first()
                else:
                    request.sucursal_activa = perfil.sucursal_defecto

        return self.get_response(request)


class ModuloAccessMiddleware:
    """Bloquea el acceso directo por URL a un módulo que el usuario no puede ver
    (no basta con ocultarlo del sidebar). Debe ir después de TenantMiddleware."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        from django.shortcuts import redirect
        from django.contrib import messages
        from .modulos import (modulo_de_resolver, modulos_visibles,
                              seccion_de_resolver, secciones_ocultas)

        if not request.user.is_authenticated:
            return None
        modulo = modulo_de_resolver(request.resolver_match)
        if not modulo:
            return None  # ruta sin módulo (home, config, usuarios, etc.)

        if modulo not in modulos_visibles(request.user, request.empresa):
            messages.error(request, "No tienes acceso a este módulo.")
            return redirect('home')

        # Capa 3: bloqueo por pantalla/sección (permiso fino por usuario)
        seccion = seccion_de_resolver(request.resolver_match)
        if seccion and seccion in secciones_ocultas(request.user, request.empresa):
            messages.error(request, "No tienes acceso a esta pantalla.")
            return redirect('home')
        return None