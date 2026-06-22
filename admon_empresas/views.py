from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Sum, F, Q

from .models import ClienteSaaS, Empresa, Moneda, Sucursal, PerfilUsuario, Impuesto, EmpresaModulo, AccesoModuloUsuario
from django.contrib.auth.models import User
from .models import PerfilUsuario
from django.contrib.auth.decorators import login_required

from .forms import SucursalForm, EmpresaForm
from django.contrib import messages

from django.views.generic import ListView, View
from .mixins import GroupRequiredMixin, StaffRequiredMixin

from django.utils import timezone
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied


class CustomLoginView(LoginView):
    template_name = 'admon_empresas/login.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['empresa'] = Empresa.objects.first()
        return ctx


# views.py
def cambiar_contexto(request, sucursal_id):
    sucursal = get_object_or_404(Sucursal, id=sucursal_id, empresa=request.empresa)
    
    # Guardamos en la sesión
    request.session['sucursal_id'] = sucursal.id
    request.session['sucursal_nombre'] = sucursal.nombre
    
    messages.info(request, f"Cambiado a sucursal: {sucursal.nombre}")
    
    # Regresamos a la página donde estaba el usuario
    return redirect(request.META.get('HTTP_REFERER', 'home'))

def cambiar_empresa(request, empresa_id):
    # Verificamos que el usuario tenga permiso de acceder a esa empresa
    # (Suponiendo que tienes una relación o el usuario es superuser)
    empresa = get_object_or_404(Empresa, id=empresa_id)
    
    # Limpiamos la sucursal anterior para evitar conflictos
    request.session.pop('sucursal_id', None)
    request.session.pop('sucursal_nombre', None)

    # Guardamos la nueva Empresa en sesión
    request.session['empresa_id'] = empresa.id
    request.session['empresa_nombre'] = empresa.nombre_fiscal
    
    # Al cambiar de empresa, buscamos su Matriz por defecto
    matriz = empresa.sucursales.filter(es_matriz=True).first()
    if matriz:
        request.session['sucursal_id'] = matriz.id
        request.session['sucursal_nombre'] = matriz.nombre

    messages.success(request, f"Cambiado a: {empresa.nombre_fiscal}")
    return redirect('home')

@login_required
def home_view(request):
    # SEGURIDAD: Si no ha aceptado la invitación (cambiado clave), no entra al home.
    # El superuser nunca pasa por el flujo de invitación, así que se excluye.
    if not request.user.is_superuser and not request.user.perfil.invitacion_aceptada:
        return redirect('cambiar_password_obligatorio')

    return render(request, 'admon_empresas/home_corporativo.html', {
        'empresa': request.empresa,
    })


@login_required
def dashboard_ejecutivo_view(request):
    """Tablero ejecutivo con los indicadores del día."""
    from datetime import date
    dash = _dashboard_data(request)
    if not dash:
        messages.info(request, "Esta empresa no tiene módulos operativos para mostrar indicadores.")
        return redirect('home')
    return render(request, 'admon_empresas/dashboard_ejecutivo.html', {
        'empresa': request.empresa,
        'dash': dash,
        'hoy': date.today(),
    })


def _dashboard_data(request):
    """Indicadores del día para la empresa activa, según módulos visibles.
    Devuelve None si no hay empresa o módulos operativos."""
    import decimal
    from datetime import date
    from .modulos import modulos_visibles

    empresa = getattr(request, 'empresa', None)
    if not empresa:
        return None
    mods = modulos_visibles(request.user, empresa)
    if not (mods & {'finanzas', 'ventas', 'compras', 'inventarios'}):
        return None

    D = decimal.Decimal
    hoy = date.today()
    mes_ini = hoy.replace(day=1)
    d = {'mods': mods, 'tiles': {}}

    # ---- Finanzas: CxC por cobrar / CxP por pagar / flujo del mes ----
    if 'finanzas' in mods:
        from admon_finanzas.models import FacturaCliente, FacturaProveedor, Pago
        cxc = FacturaCliente.objects.filter(empresa=empresa).exclude(estado='CANCELADA').select_related('cliente')
        pend_cxc = [f for f in cxc if f.saldo > 0]
        d['cxc_total'] = sum((f.saldo for f in pend_cxc), D('0'))
        d['cxc_count'] = len(pend_cxc)
        d['cxc_venc'] = sum((f.saldo for f in pend_cxc if f.fecha_vencimiento and f.fecha_vencimiento < hoy), D('0'))
        d['cxc_top'] = sorted(pend_cxc, key=lambda f: f.saldo, reverse=True)[:5]

        cxp = FacturaProveedor.objects.filter(empresa=empresa).exclude(estado='CANCELADA').select_related('proveedor')
        pend_cxp = [f for f in cxp if f.saldo > 0]
        d['cxp_total'] = sum((f.saldo for f in pend_cxp), D('0'))
        d['cxp_count'] = len(pend_cxp)

        pagos = Pago.objects.filter(empresa=empresa, fecha__gte=mes_ini)
        d['cobrado_mes'] = sum((p.monto for p in pagos if p.tipo == 'INGRESO'), D('0'))
        # Egresos del mes excluyendo compras de uso personal
        personales = set(Pago.objects.filter(
            empresa=empresa, tipo='EGRESO',
            aplicaciones__factura__orden_compra__uso_personal=True
        ).values_list('id', flat=True))
        d['pagado_mes'] = sum((p.monto for p in pagos
                               if p.tipo == 'EGRESO' and p.id not in personales), D('0'))
        d['flujo_neto_mes'] = d['cobrado_mes'] - d['pagado_mes']

        # ---- Antigüedad (aging) de CxC y CxP: por vencer vs vencido por tramos ----
        def _aging(pendientes):
            b = {'por_vencer': D('0'), 'd1_30': D('0'), 'd31_60': D('0'),
                 'd60': D('0'), 'vencido': D('0')}
            for f in pendientes:
                venc = f.fecha_vencimiento
                if not venc or venc >= hoy:
                    b['por_vencer'] += f.saldo
                else:
                    dias = (hoy - venc).days
                    b['vencido'] += f.saldo
                    if dias <= 30:
                        b['d1_30'] += f.saldo
                    elif dias <= 60:
                        b['d31_60'] += f.saldo
                    else:
                        b['d60'] += f.saldo
            return b
        d['cxc_aging'] = _aging(pend_cxc)
        d['cxp_aging'] = _aging(pend_cxp)
        d['cxp_venc'] = d['cxp_aging']['vencido']

    # ---- Ventas: facturado del mes + pedidos por estado + margen + top productos ----
    if 'ventas' in mods:
        from admon_ventas.models import Pedido, DetallePedido
        from admon_finanzas.models import FacturaCliente
        ventas_mes = FacturaCliente.objects.filter(
            empresa=empresa, fecha_emision__gte=mes_ini).exclude(estado='CANCELADA')
        d['ventas_mes'] = sum((f.total for f in ventas_mes), D('0'))
        peds = Pedido.objects.filter(empresa=empresa)
        d['ped_borrador'] = peds.filter(estado='BORRADOR').count()
        d['ped_confirmado'] = peds.filter(estado__in=['CONFIRMADO', 'ENTREGADO_PARCIAL']).count()
        d['ped_entregado'] = peds.filter(estado='ENTREGADO').count()

        # Margen del mes (sobre lo entregado, sin IVA): venta − costo
        dets = DetallePedido.objects.filter(
            pedido__empresa=empresa,
            pedido__estado__in=['ENTREGADO', 'ENTREGADO_PARCIAL'],
            pedido__fecha_emision__gte=mes_ini).select_related('producto')
        venta_neta = D('0'); costo_neto = D('0'); top = {}
        for det in dets:
            qty = det.cantidad_entregada or D('0')
            if qty <= 0:
                continue
            v = qty * det.precio_unitario
            c = qty * (det.producto.costo_unitario or D('0'))
            venta_neta += v; costo_neto += c
            t = top.setdefault(det.producto_id, {
                'nombre': det.producto.nombre, 'sku': det.producto.sku,
                'cant': D('0'), 'venta': D('0'), 'ganancia': D('0')})
            t['cant'] += qty; t['venta'] += v; t['ganancia'] += (v - c)
        d['venta_neta_mes'] = venta_neta
        d['ganancia_mes'] = venta_neta - costo_neto
        d['margen_mes'] = (d['ganancia_mes'] / venta_neta * 100) if venta_neta else D('0')
        d['top_productos'] = sorted(top.values(), key=lambda x: x['venta'], reverse=True)[:5]

    # ---- Compras: órdenes abiertas ----
    if 'compras' in mods:
        from admon_compras.models import OrdenCompra
        abiertas = OrdenCompra.objects.filter(
            empresa=empresa, estado__in=['BORRADOR', 'SOLICITADO', 'AUTORIZADO', 'RECIBIDO'])
        d['oc_abiertas'] = abiertas.count()
        d['oc_monto'] = sum((o.total for o in abiertas), D('0'))

    # ---- Inventario: SKUs, valor y alertas de stock mínimo ----
    if 'inventarios' in mods:
        from admon_inventarios.models import Producto, Existencia, ProductoSucursal
        from django.db.models import Sum, F
        # Solo productos vendibles (excluye los de uso personal y no vendibles)
        d['skus'] = Producto.objects.filter(
            empresa=empresa, activo=True, es_vendible=True).count()
        ex = Existencia.objects.filter(
            producto__empresa=empresa, cantidad__gt=0, producto__es_vendible=True)
        d['skus_con_stock'] = ex.values('producto').distinct().count()
        valor = ex.aggregate(v=Sum(F('cantidad') * F('producto__costo_unitario')))['v']
        d['inv_valor'] = valor or D('0')
        # Valor potencial de venta y ganancia latente (a precio de lista)
        valor_venta = ex.aggregate(v=Sum(F('cantidad') * F('producto__precio_venta')))['v'] or D('0')
        d['inv_valor_venta'] = valor_venta
        d['inv_ganancia_latente'] = valor_venta - d['inv_valor']
        d['inv_margen_latente'] = (d['inv_ganancia_latente'] / valor_venta * 100) if valor_venta else D('0')

        # Alertas: productos con stock mínimo definido y existencia por debajo
        alertas = []
        configs = ProductoSucursal.objects.filter(
            producto__empresa=empresa, stock_minimo__gt=0).select_related('producto', 'sucursal')
        for cfg in configs:
            actual = Existencia.objects.filter(
                producto=cfg.producto, sucursal=cfg.sucursal).aggregate(s=Sum('cantidad'))['s'] or D('0')
            if actual < cfg.stock_minimo:
                alertas.append({'producto': cfg.producto.nombre, 'sku': cfg.producto.sku,
                                'sucursal': cfg.sucursal.nombre, 'actual': actual,
                                'minimo': cfg.stock_minimo})
        d['alertas_stock'] = alertas[:8]
        d['alertas_count'] = len(alertas)

    return d

def registro_cliente_view(request, token):
    cliente = get_object_or_404(ClienteSaaS, token_invitacion=token, registro_completado=False)

    if request.method == 'POST':
        nombre_fiscal = request.POST.get('nombre_fiscal')
        rfc = request.POST.get('rfc').upper()
        password = request.POST.get('password')
        username = request.POST.get('username')

        # --- CAMBIO CLAVE AQUÍ ---
        # 2. Intentamos buscar si el usuario ya existe para no duplicarlo
        user = User.objects.filter(username=username).first()

        if not user:
            # Si no existe, lo creamos de cero
            user = User.objects.create_user(
                username=username, 
                email=cliente.email_contacto, 
                password=password,
                first_name=request.POST.get('first_name'), 
                last_name=request.POST.get('last_name')
            )
            messages.info(request, "Usuario nuevo creado.")
        else:
            # Si ya existe, podrías validar la contraseña o simplemente 
            # vincular la nueva empresa al usuario existente.
            messages.info(request, "Usuario existente detectado. Vinculando nueva empresa...")

        # 3. Crear la Empresa (Esto siempre se crea nuevo)
        nueva_empresa = Empresa.objects.create(
            cliente=cliente,
            nombre_fiscal=nombre_fiscal,
            rfc=rfc
        )

        # 4. Crear la Sucursal Matriz
        matriz = Sucursal.objects.create(
            empresa=nueva_empresa,
            nombre=request.POST.get('nombre_sucursal'),
            es_matriz=True,
            codigo_sucursal="MATRIZ"
        )

        # 5. Vincular Usuario con la Empresa (ManyToMany)
        # Nota: El signal OneToOne solo actúa la PRIMERA VEZ que se crea el User.
        # Si el usuario ya existía, solo recuperamos su perfil.
        perfil = user.perfil 
        
        perfil.empresas.add(nueva_empresa) 
        
        # Si es su primera empresa, la marcamos como default
        # Usamos perfil.empresa_default (el campo del modelo)
        if not perfil.empresa_default:
            perfil.empresa_default = nueva_empresa
            perfil.sucursal_defecto = matriz
        
        perfil.tipo_usuario = 'OWNER'
        # El cliente ya eligió su contraseña durante el registro,
        # no debe ser forzado a cambiarla al primer login.
        perfil.invitacion_aceptada = True
        perfil.save()

        # 6. Finalizar proceso
        cliente.registro_completado = True
        cliente.save()

        return render(request, 'admon_empresas/exito.html')

    return render(request, 'admon_empresas/registro_empresa.html', {'cliente': cliente})

def registro_cliente_view_todel(request, token):
    cliente = get_object_or_404(ClienteSaaS, token_invitacion=token, registro_completado=False)

    if request.method == 'POST':
        # 1. Capturar datos del formulario
        nombre_fiscal = request.POST.get('nombre_fiscal')
        rfc = request.POST.get('rfc').upper()
        password = request.POST.get('password')
        username = request.POST.get('username') # Sugerencia: usar su email

        # 2. Crear el Usuario de Django (Dueño)
        user = User.objects.create_user(
            username=username, 
            email=cliente.email_contacto, 
            password=password,
            first_name=request.POST.get('first_name'), 
            last_name=request.POST.get('last_name')
        )

        # 3. Crear la Empresa
        nueva_empresa = Empresa.objects.create(
            cliente=cliente,
            nombre_fiscal=nombre_fiscal,
            rfc=rfc
        )

        # 4. Crear la Sucursal Matriz
        matriz = Sucursal.objects.create(
            empresa=nueva_empresa,
            nombre=request.POST.get('nombre_sucursal'),
            es_matriz=True,
            codigo_sucursal="MATRIZ"
        )

        # 5. Vincular Usuario con la Empresa a través del Perfil
        # El signal ya creó el perfil, así que solo lo actualizamos
        perfil = user.perfil
        perfil.nombre = request.POST.get('first_name')
        perfil.apellido = request.POST.get('last_name')
        request.empresa = nueva_empresa
        perfil.sucursal_defecto = matriz  # <--- AGREGA ESTA LÍNEA
        perfil.tipo_usuario = 'OWNER'
        perfil.save()

        # 6. Finalizar proceso
        cliente.registro_completado = True
        cliente.save()

        return render(request, 'admon_empresas/exito.html')

    return render(request, 'admon_empresas/registro_empresa.html', {'cliente': cliente})

class DashboardView(StaffRequiredMixin, ListView):
    template_name = 'admon_empresas/panel_indicadores.html'
    model = Sucursal 

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        empresa = self.request.empresa
        hoy = timezone.now()
        
        # 1. Moneda y Sucursales (Lo que ya tenías)
        moneda_base = empresa.moneda_principal
        context['total_sucursales'] = empresa.sucursales.count()
        context['total_monedas'] = empresa.monedas_empresa.count()
        context['moneda_simbolo'] = moneda_base.simbolo if moneda_base else '$'
        context['moneda_codigo'] = moneda_base.codigo if moneda_base else '---'
        
        

        # Inyectamos al contexto        
        context['seccion'] = 'dashboard'
        
        return context

class ConfiguracionView(GroupRequiredMixin, View):
    template_name = 'admon_empresas/configuracion.html'
    group_required = ['Dueños', 'Administradores']

    def get(self, request):
        # USAMOS EL REQUEST (Inyectado por el Middleware)
        empresa = request.empresa 
        
        if not empresa:
            messages.error(request, "No hay una empresa activa seleccionada.")
            return redirect('home')

        active_tab = request.session.pop('active_tab', 'empresa')

        #context = {
        #    'form_sucursal': SucursalForm(),
        #    'form_empresa': EmpresaForm(instance=empresa),
        #    'sucursales': Sucursal.objects.filter(empresa=empresa),
        #    'monedas': Moneda.objects.filter(empresa=empresa),
        #    'empresa': empresa,
        #    'seccion': 'config',
        #    'active_tab': active_tab
        #}
        context = self.get_context(request, active_tab)
        return render(request, self.template_name, context)

    def post(self, request):
        # USAMOS EL REQUEST
        empresa = request.empresa
        action = request.POST.get('action')
    
        if action == 'delete_item':
            item_id = request.POST.get('item_id')
            tipo = request.POST.get('tipo_objeto')
            
            if tipo == 'sucursal':
                obj = get_object_or_404(Sucursal, id=item_id, empresa=empresa)
                request.session['active_tab'] = 'sucursales'
            elif tipo == 'moneda':
                obj = get_object_or_404(Moneda, id=item_id, empresa=empresa)
                request.session['active_tab'] = 'monedas'
            elif tipo == 'impuesto':
                obj = get_object_or_404(Impuesto, id=item_id, empresa=empresa)
                request.session['active_tab'] = 'impuestos'

            obj.delete()
            messages.success(request, f"Registro eliminado correctamente.")
            return redirect('configuracion')       

        # --- LÓGICA PARA SUCURSALES ---
        elif 'btn_sucursal' in request.POST:
            sucursal_id = request.POST.get('sucursal_id')
            
            # IMPORTANTE: Antes de cualquier cosa, le decimos a la sesión que regrese aquí
            request.session['active_tab'] = 'sucursales'
            
            if sucursal_id:
                # Lógica de EDICIÓN (La que ya tienes)
                instance = get_object_or_404(Sucursal, id=sucursal_id, empresa=empresa)
                instance.nombre = request.POST.get('nombre')
                instance.codigo_sucursal = request.POST.get('codigo_sucursal')
                
                ubic_id = request.POST.get('ubicacion_recepcion_defecto')
                instance.ubicacion_recepcion_defecto_id = ubic_id if ubic_id else None
                instance.save()
                messages.success(request, "Sucursal actualizada.")
            else:
                # Lógica de CREACIÓN
                form = SucursalForm(request.POST)
                if form.is_valid():
                    nueva_suc = form.save(commit=False)
                    nueva_suc.empresa = empresa
                    # CAPTURAMOS LA UBICACIÓN TAMBIÉN AQUÍ:
                    ubic_id = request.POST.get('ubicacion_recepcion_defecto')
                    if ubic_id:
                        nueva_suc.ubicacion_recepcion_defecto_id = ubic_id
                    nueva_suc.save()
                    messages.success(request, "¡Sucursal creada!")
            
            return redirect('configuracion')
        
        elif 'btn_empresa' in request.POST:
            form = EmpresaForm(request.POST, request.FILES, instance=empresa)
            if form.is_valid():
                form.save()
                messages.success(request, "Datos actualizados.")
                return redirect('configuracion')

        elif 'btn_moneda' in request.POST:
            nombre = request.POST.get('nombre_moneda')
            codigo = request.POST.get('codigo_moneda')
            simbolo = request.POST.get('simbolo_moneda')
            
            if nombre and codigo:
                Moneda.objects.create(
                    empresa=empresa, # <--- IMPORTANTE: Usar la empresa del request
                    nombre=nombre,
                    codigo=codigo.upper(),
                    simbolo=simbolo if simbolo else '$'
                )
                messages.success(request, f"Moneda {codigo} agregada.")
            
            context = self.get_context(request, 'monedas')
            return render(request, self.template_name, context)

        elif 'btn_modulos' in request.POST:
            if not request.user.is_superuser:
                messages.error(request, "Solo el administrador puede cambiar los módulos contratados.")
                return redirect('configuracion')
            from .modulos import MODULOS_DISPONIBLES
            marcados = set(request.POST.getlist('modulos[]'))
            for m in MODULOS_DISPONIBLES:
                EmpresaModulo.objects.update_or_create(
                    empresa=empresa, modulo=m['clave'],
                    defaults={'activo': m['clave'] in marcados})
            messages.success(request, "Módulos de la empresa actualizados.")
            request.session['active_tab'] = 'modulos'
            return redirect('configuracion')

        elif 'btn_impuesto' in request.POST:
            import decimal
            nombre = request.POST.get('nombre_impuesto')
            tasa = request.POST.get('tasa_impuesto') or '0'
            tipo_factor = request.POST.get('tipo_factor') or 'TASA'
            es_retencion = request.POST.get('es_retencion') == 'on'
            es_default = request.POST.get('es_default') == 'on'
            if nombre:
                Impuesto.objects.create(
                    empresa=empresa, nombre=nombre,
                    tasa=decimal.Decimal(tasa), tipo_factor=tipo_factor,
                    es_retencion=es_retencion, es_default=es_default)
                messages.success(request, f"Impuesto '{nombre}' agregado.")
            request.session['active_tab'] = 'impuestos'
            return redirect('configuracion')

        return redirect('configuracion')

    def get_context(self, request, active_tab='empresa'):
        # TAMBIÉN AQUÍ: Usar request.empresa
        empresa = request.empresa
        return {
            'form_sucursal': SucursalForm(),
            'form_empresa': EmpresaForm(instance=empresa),
            'sucursales': Sucursal.objects.filter(empresa=empresa),
            'monedas': Moneda.objects.filter(empresa=empresa),
            'impuestos': Impuesto.objects.filter(empresa=empresa),
            'modulos_empresa': self._modulos_empresa(empresa),
            'empresa': empresa,
            'seccion': 'config',
            'active_tab': active_tab
        }

    def _modulos_empresa(self, empresa):
        from .modulos import MODULOS_DISPONIBLES
        activos = set(EmpresaModulo.objects.filter(
            empresa=empresa, activo=True).values_list('modulo', flat=True))
        return [{'clave': m['clave'], 'nombre': m['nombre'], 'icono': m['icono'],
                 'activo': m['clave'] in activos} for m in MODULOS_DISPONIBLES]
    
# EDITAR SUCURSAL    
def editar_sucursal(request, pk):
    # Buscamos la sucursal asegurando que pertenezca a la empresa del usuario
    sucursal = get_object_or_404(Sucursal, pk=pk, empresa=request.empresa)
    
    if request.method == 'POST':
        form = SucursalForm(request.POST, instance=sucursal)
        if form.is_valid():
            form.save()
            messages.success(request, f"Sucursal '{sucursal.nombre}' actualizada.")
            # Usamos un truco: guardamos en la sesión a qué pestaña volver
            request.session['active_tab'] = 'sucursales'
            return redirect('configuracion')
    
    # Si quieres hacerlo con un modal, esta parte se manejaría distinto, 
    # pero para una edición rápida esta es la base.
    return redirect('configuracion')

# ELIMINAR SUCURSAL
def eliminar_sucursal(request, pk):
    sucursal = get_object_or_404(Sucursal, pk=pk, empresa=request.empresa)
    sucursal.delete()
    messages.warning(request, "Sucursal eliminada correctamente.")
    return redirect('configuracion')

# EDITAR MONEDA
def editar_moneda(request, pk):
    moneda = get_object_or_404(Moneda, pk=pk, empresa=request.empresa)
    
    if request.method == 'POST':
        # Nota: Aquí puedes usar un MonedaForm si lo creaste, o actualizar campos manual
        moneda.nombre = request.POST.get('nombre')
        moneda.codigo = request.POST.get('codigo').upper()
        moneda.simbolo = request.POST.get('simbolo')
        moneda.save()
        
        messages.success(request, f"Moneda {moneda.codigo} actualizada.")
        request.session['active_tab'] = 'monedas' # <--- Importante para volver aquí
        return redirect('configuracion')
    
    return redirect('configuracion')

# ELIMINAR MONEDA
def eliminar_moneda(request, pk):
    moneda = get_object_or_404(Moneda, pk=pk, empresa=request.empresa)
    if moneda.es_principal:
        messages.error(request, "No puedes eliminar la moneda principal.")
    else:
        moneda.delete()
        messages.warning(request, "Moneda eliminada.")
    return redirect('configuracion')

# EDITAR IMPUESTO
def editar_impuesto(request, pk):
    import decimal
    impuesto = get_object_or_404(Impuesto, pk=pk, empresa=request.empresa)
    if request.method == 'POST':
        impuesto.nombre = request.POST.get('nombre')
        impuesto.tasa = decimal.Decimal(request.POST.get('tasa') or '0')
        impuesto.tipo_factor = request.POST.get('tipo_factor') or 'TASA'
        impuesto.es_retencion = request.POST.get('es_retencion') == 'on'
        impuesto.es_default = request.POST.get('es_default') == 'on'
        impuesto.save()
        messages.success(request, f"Impuesto '{impuesto.nombre}' actualizado.")
        request.session['active_tab'] = 'impuestos'
    return redirect('configuracion')


# ─── GESTIÓN DE CLIENTES (solo superuser) ────────────────────────────────────

def _superuser_required(view_func):
    """Decorador simple: solo superusers."""
    from functools import wraps
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return login_required(wrapper)


@_superuser_required
def lista_clientes(request):
    from .emails import url_registro_cliente
    clientes = list(ClienteSaaS.objects.prefetch_related('empresas__sucursales').all())
    for c in clientes:
        c.registro_url = url_registro_cliente(c)
    return render(request, 'admon_empresas/clientes/lista.html', {'clientes': clientes})


@_superuser_required
def reenviar_invitacion(request, pk):
    cliente = get_object_or_404(ClienteSaaS, pk=pk)
    from .emails import enviar_invitacion_cliente
    if cliente.registro_completado:
        messages.info(request, "Este cliente ya completó su registro.")
    elif not cliente.email_contacto:
        messages.error(request, "El cliente no tiene email de contacto; copia el link e invítalo manualmente.")
    elif enviar_invitacion_cliente(cliente):
        messages.success(request, f"Invitación reenviada a {cliente.email_contacto}.")
    else:
        messages.error(request, "No se pudo enviar el correo. Copia el link de invitación manualmente.")
    return redirect('lista_clientes')


@_superuser_required
def crear_cliente(request):
    if request.method == 'POST':
        nombre = request.POST.get('nombre_comercial', '').strip()
        slug = request.POST.get('slug_instancia', '').strip()
        email = request.POST.get('email_contacto', '').strip()
        if not nombre or not slug:
            messages.error(request, 'Nombre y slug son obligatorios.')
            return render(request, 'admon_empresas/clientes/form_cliente.html')
        if ClienteSaaS.objects.filter(slug_instancia=slug).exists():
            messages.error(request, f'El slug "{slug}" ya está en uso.')
            return render(request, 'admon_empresas/clientes/form_cliente.html')
        ClienteSaaS.objects.create(nombre_comercial=nombre, slug_instancia=slug, email_contacto=email or None)
        messages.success(request, f'Cliente "{nombre}" creado.')
        return redirect('lista_clientes')
    return render(request, 'admon_empresas/clientes/form_cliente.html')


@_superuser_required
def editar_cliente(request, pk):
    cliente = get_object_or_404(ClienteSaaS, pk=pk)
    if request.method == 'POST':
        cliente.nombre_comercial = request.POST.get('nombre_comercial', '').strip()
        cliente.email_contacto = request.POST.get('email_contacto', '').strip() or None
        cliente.save()
        messages.success(request, 'Cliente actualizado.')
        return redirect('lista_clientes')
    return render(request, 'admon_empresas/clientes/form_cliente.html', {'cliente': cliente})


@_superuser_required
def eliminar_cliente(request, pk):
    cliente = get_object_or_404(ClienteSaaS, pk=pk)
    if request.method == 'POST':
        nombre = cliente.nombre_comercial
        cliente.delete()
        messages.warning(request, f'Cliente "{nombre}" y todos sus datos eliminados.')
        return redirect('lista_clientes')
    return render(request, 'admon_empresas/clientes/confirmar_eliminar.html', {'cliente': cliente})


@_superuser_required
def crear_empresa(request, cliente_pk):
    cliente = get_object_or_404(ClienteSaaS, pk=cliente_pk)
    if request.method == 'POST':
        nombre_fiscal = request.POST.get('nombre_fiscal', '').strip()
        rfc = request.POST.get('rfc', '').strip().upper()
        color = request.POST.get('color_primario', 'indigo')
        logo = request.FILES.get('logo')
        nombre_sucursal = request.POST.get('nombre_sucursal', '').strip()
        codigo_sucursal = request.POST.get('codigo_sucursal', '').strip().upper()
        if not nombre_fiscal or not rfc or not nombre_sucursal or not codigo_sucursal:
            messages.error(request, 'Todos los campos marcados con * son obligatorios.')
            return render(request, 'admon_empresas/clientes/form_empresa.html', {'cliente': cliente})
        empresa = Empresa.objects.create(cliente=cliente, nombre_fiscal=nombre_fiscal, rfc=rfc, color_primario=color)
        if logo:
            empresa.logo = logo
            empresa.save()
        Sucursal.objects.create(empresa=empresa, nombre=nombre_sucursal, codigo_sucursal=codigo_sucursal, es_matriz=True)
        messages.success(request, f'Empresa "{nombre_fiscal}" creada con sucursal matriz.')
        return redirect('lista_clientes')
    return render(request, 'admon_empresas/clientes/form_empresa.html', {'cliente': cliente})


@_superuser_required
def eliminar_empresa(request, pk):
    empresa = get_object_or_404(Empresa, pk=pk)
    if request.method == 'POST':
        nombre = empresa.nombre_fiscal
        empresa.delete()
        messages.warning(request, f'Empresa "{nombre}" y sus sucursales eliminadas.')
        return redirect('lista_clientes')
    return render(request, 'admon_empresas/clientes/confirmar_eliminar_empresa.html', {'empresa': empresa})


@_superuser_required
def crear_sucursal_cliente(request, empresa_pk):
    empresa = get_object_or_404(Empresa, pk=empresa_pk)
    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        codigo = request.POST.get('codigo_sucursal', '').strip().upper()
        es_matriz = request.POST.get('es_matriz') == 'on'
        if not nombre or not codigo:
            messages.error(request, 'Nombre y código son obligatorios.')
            return render(request, 'admon_empresas/clientes/form_sucursal.html', {'empresa': empresa})
        Sucursal.objects.create(empresa=empresa, nombre=nombre, codigo_sucursal=codigo, es_matriz=es_matriz)
        messages.success(request, f'Sucursal "{nombre}" creada.')
        return redirect('lista_clientes')
    return render(request, 'admon_empresas/clientes/form_sucursal.html', {'empresa': empresa})


@_superuser_required
def editar_sucursal_cliente(request, pk):
    sucursal = get_object_or_404(Sucursal, pk=pk)
    empresa = sucursal.empresa
    if request.method == 'POST':
        sucursal.nombre = request.POST.get('nombre', '').strip()
        sucursal.codigo_sucursal = request.POST.get('codigo_sucursal', '').strip().upper()
        es_matriz = request.POST.get('es_matriz') == 'on'
        if es_matriz:
            # Solo una puede ser matriz — quitarla a las demás
            empresa.sucursales.exclude(pk=sucursal.pk).update(es_matriz=False)
        sucursal.es_matriz = es_matriz
        sucursal.save()
        messages.success(request, f'Sucursal "{sucursal.nombre}" actualizada.')
        return redirect('lista_clientes')
    return render(request, 'admon_empresas/clientes/form_editar_sucursal.html', {
        'sucursal': sucursal,
        'empresa': empresa,
    })


@_superuser_required
def eliminar_sucursal_cliente(request, pk):
    sucursal = get_object_or_404(Sucursal, pk=pk)
    if request.method == 'POST':
        nombre = sucursal.nombre
        sucursal.delete()
        messages.warning(request, f'Sucursal "{nombre}" eliminada.')
        return redirect('lista_clientes')
    return render(request, 'admon_empresas/clientes/confirmar_eliminar_sucursal.html', {'sucursal': sucursal})
