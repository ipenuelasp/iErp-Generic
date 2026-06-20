class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Inicializamos con valores por defecto para evitar el error de "no attribute"
        request.empresa = None
        request.empresas = [] # <--- AÑADE ESTO
        request.sucursal_activa = None

        if request.user.is_authenticated:
            perfil = getattr(request.user, 'perfil', None)
            
            if perfil:
                # 1. Inyectamos la lista completa de empresas permitidas
                request.empresas = perfil.empresas.all() # <--- AÑADE ESTO

                empresa_id = request.session.get('empresa_id')
                
                # 2. Buscamos la empresa activa
                if empresa_id:
                    empresa = perfil.empresas.filter(id=int(empresa_id)).first()
                else:
                    empresa = perfil.empresa_default
                    if empresa:
                        request.session['empresa_id'] = empresa.id

                request.empresa = empresa 

                # 3. Sucursal Activa
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
        from .modulos import modulo_de_resolver, modulos_visibles

        if not request.user.is_authenticated:
            return None
        modulo = modulo_de_resolver(request.resolver_match)
        if not modulo:
            return None  # ruta sin módulo (home, config, usuarios, etc.)

        if modulo not in modulos_visibles(request.user, request.empresa):
            messages.error(request, "No tienes acceso a este módulo.")
            return redirect('home')
        return None