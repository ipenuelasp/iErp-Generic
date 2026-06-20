# admon_empresas/context_processors.py
from admon_empresas.models import Empresa

def empresa_context(request):
    if request.user.is_authenticated:
        try:
            perfil = getattr(request.user, 'perfil', None)
            if not perfil:
                return {}

            # 1. Determinar la Empresa Actual
            empresa_id = request.session.get('empresa_id')
            if empresa_id:
                empresa = perfil.empresas.filter(id=empresa_id).first()
                if not empresa: # Seguridad: Si la empresa en sesión no es del usuario
                    empresa = perfil.empresa_default
            else:
                empresa = perfil.empresa_default
            
            # Si aún no hay empresa (raro), intentamos la primera permitida
            if not empresa:
                empresa = perfil.empresas.first()

            if empresa:
                request.session['empresa_id'] = empresa.id

            # 2. FILTRADO CRÍTICO: Solo empresas donde el usuario tiene al menos una sucursal
            mis_empresas = Empresa.objects.filter(
                id__in=perfil.sucursales.values('empresa_id')
            ).distinct()
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
            
            # 5. Módulos visibles para este usuario en la empresa activa
            from .modulos import modulos_visibles
            mods = modulos_visibles(request.user, empresa)

            return {
                'empresa': empresa,
                'mis_empresas': mis_empresas,
                'sucursales_nav': sucursales_nav,
                'brand_color': seleccion['base'],
                'brand_color_dark': seleccion['dark'],
                'modulos_visibles': mods,
            }
        except Exception as e:
            print(f"Error en context_processor: {e}")
            return {}
    return {}