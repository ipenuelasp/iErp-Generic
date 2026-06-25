# admon_empresas/context_processors.py
from admon_empresas.models import Empresa

def empresa_context(request):
    if request.user.is_authenticated:
        try:
            perfil = getattr(request.user, 'perfil', None)
            if not perfil:
                return {}

            # Tenant del subdominio (lo resuelve TenantMiddleware). Acota TODO.
            tenant = getattr(request, 'tenant', None)
            empresas_permitidas = perfil.empresas.all()
            if tenant:
                empresas_permitidas = empresas_permitidas.filter(cliente=tenant)

            # 1. Determinar la Empresa Actual (siempre dentro de lo permitido/acotado)
            empresa_id = request.session.get('empresa_id')
            if empresa_id:
                empresa = empresas_permitidas.filter(id=empresa_id).first()
                if not empresa: # Seguridad: si la empresa en sesión no es del tenant/usuario
                    empresa = empresas_permitidas.first()
            else:
                dflt = perfil.empresa_default
                empresa = (empresas_permitidas.filter(id=dflt.id).first() if dflt else None) \
                    or empresas_permitidas.first()

            if empresa:
                request.session['empresa_id'] = empresa.id

            # 2. FILTRADO CRÍTICO: empresas del usuario (con sucursal) acotadas al tenant
            mis_empresas = Empresa.objects.filter(
                id__in=perfil.sucursales.values('empresa_id')
            ).distinct()
            if tenant:
                mis_empresas = mis_empresas.filter(cliente=tenant)
            # Filtramos sucursales: Solo las que pertenecen a la empresa actual Y el usuario tiene permiso
            sucursales_nav = perfil.sucursales.filter(empresa=empresa).distinct()

            # 3. Configuración de Colores (Tu lógica existente)
            colores = {
                'indigo': {'base': '#6366f1', 'dark': '#4f46e5'},
                'blue':   {'base': '#00ABF1', 'dark': '#0086bc'},
                'emerald':{'base': '#10b981', 'dark': '#059669'},
                'rose':   {'base': '#f43f5e', 'dark': '#e11d48'},
                'slate':  {'base': '#475569', 'dark': '#334155'},
            }
            
            color_key = empresa.color_primario if empresa else 'indigo'
            seleccion = colores.get(color_key, colores['indigo'])

            # 4. Sucursal por defecto en sesión
            if 'sucursal_id' not in request.session and empresa:
                # Prioridad a la sucursal_defecto del perfil si pertenece a esta empresa
                if perfil.sucursal_defecto and perfil.sucursal_defecto.empresa == empresa:
                    request.session['sucursal_id'] = perfil.sucursal_defecto.id
                    request.session['sucursal_nombre'] = perfil.sucursal_defecto.nombre
                else:
                    matriz = sucursales_nav.filter(es_matriz=True).first() or sucursales_nav.first()
                    if matriz:
                        request.session['sucursal_id'] = matriz.id
                        request.session['sucursal_nombre'] = matriz.nombre
            
            # 5. Módulos visibles + secciones ocultas (permiso fino) para este usuario
            from .modulos import modulos_visibles, secciones_ocultas
            mods = modulos_visibles(request.user, empresa)
            ocultas = secciones_ocultas(request.user, empresa)

            return {
                'empresa': empresa,
                'mis_empresas': mis_empresas,
                'sucursales_nav': sucursales_nav,
                'brand_color': seleccion['base'],
                'brand_color_dark': seleccion['dark'],
                'modulos_visibles': mods,
                'secciones_ocultas': ocultas,
            }
        except Exception as e:
            print(f"Error en context_processor: {e}")
            return {}
    return {}