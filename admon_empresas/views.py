from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Sum, F, Q

from .models import ClienteSaaS, Empresa, Moneda, Sucursal, PerfilUsuario
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
        'empresa': request.empresa
    })

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

        return redirect('configuracion')

    def get_context(self, request, active_tab='empresa'):
        # TAMBIÉN AQUÍ: Usar request.empresa
        empresa = request.empresa
        return {
            'form_sucursal': SucursalForm(),
            'form_empresa': EmpresaForm(instance=empresa),
            'sucursales': Sucursal.objects.filter(empresa=empresa),
            'monedas': Moneda.objects.filter(empresa=empresa),
            'empresa': empresa,
            'seccion': 'config',
            'active_tab': active_tab
        }
    
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
    clientes = ClienteSaaS.objects.prefetch_related('empresas__sucursales').all()
    return render(request, 'admon_empresas/clientes/lista.html', {'clientes': clientes})


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
