from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.contrib import messages
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash, logout as auth_logout
from django.contrib.auth.models import Group

from admon_empresas.models import Sucursal, PerfilUsuario
from admon_empresas.emails import send_html


def enviar_correo_bienvenida(user, request):
    nombre = user.first_name if user.first_name else user.username
    empresa_nombre = user.perfil.empresa_default.nombre_fiscal if user.perfil.empresa_default else "iErp"
    return send_html(
        subject=f"Bienvenido a iErp - Acceso para {nombre}",
        template='admon_usuarios/emails/bienvenida_usuario.html',
        context={
            'nombre': nombre,
            'username': user.username,
            'url_login': request.build_absolute_uri('/'),
            'empresa': empresa_nombre,
        },
        to=user.email,
        request=request,
    )

@login_required
def gestion_usuarios(request):
    perfil_logueado = request.user.perfil

    # 1. SEGURIDAD: Solo Superuser o Dueños autorizados
    es_dueno_autorizado = (perfil_logueado.tipo_usuario == 'OWNER' and perfil_logueado.puede_gestionar_usuarios)
    if not (request.user.is_superuser or es_dueno_autorizado):
        raise PermissionDenied("No tienes autorización para gestionar personal.")

    # 2. FILTRADO: ¿Qué usuarios y sucursales puede ver?
    if request.user.is_superuser:
        empleados = User.objects.all().select_related('perfil')
        sucursales = Sucursal.objects.all() 
    else:
        empleados = User.objects.filter(
            perfil__empresa_default=perfil_logueado.empresa_default
        ).select_related('perfil')
        sucursales = Sucursal.objects.filter(empresa=perfil_logueado.empresa_default)

    grupos = Group.objects.all()

    # Empresas con sus sucursales para el selector del modal
    from admon_empresas.models import Empresa
    if request.user.is_superuser:
        empresas_con_sucursales = Empresa.objects.prefetch_related('sucursales').all()
    else:
        empresas_con_sucursales = perfil_logueado.empresas.prefetch_related('sucursales').all()

    # Pre-calcular accesos por empresa para cada empleado: {user_id: [(empresa, [sucursales])}
    accesos_por_usuario = {}
    for emp in empleados:
        p = emp.perfil
        empresas_emp = p.empresas.all()
        sucs_emp = list(p.sucursales.all().select_related('empresa'))
        fila = []
        for empresa in empresas_emp:
            sucs_de_empresa = [s for s in sucs_emp if s.empresa_id == empresa.id]
            fila.append({'empresa': empresa, 'sucursales': sucs_de_empresa})
        accesos_por_usuario[emp.id] = fila

    # Módulos contratados por la empresa del gestor (para repartir entre usuarios)
    from admon_empresas.modulos import MODULOS_DISPONIBLES
    from admon_empresas.models import EmpresaModulo, AccesoModuloUsuario
    empresa_gestor = perfil_logueado.empresa_default
    contratados = set(EmpresaModulo.objects.filter(
        empresa=empresa_gestor, activo=True).values_list('modulo', flat=True)) if empresa_gestor else set()
    modulos_empresa = [m for m in MODULOS_DISPONIBLES if m['clave'] in contratados]

    # Módulos ya asignados a cada empleado (en la empresa del gestor)
    from admon_empresas.modulos import secciones_de_modulo
    from admon_empresas.models import SeccionOcultaUsuario
    modulos_por_usuario = {}
    ocultas_por_usuario = {}
    if empresa_gestor:
        for emp in empleados:
            modulos_por_usuario[emp.id] = list(AccesoModuloUsuario.objects.filter(
                usuario=emp, empresa=empresa_gestor).values_list('modulo', flat=True))
            ocultas_por_usuario[emp.id] = list(SeccionOcultaUsuario.objects.filter(
                usuario=emp, empresa=empresa_gestor).values_list('seccion', flat=True))
    # Secciones (pantallas) por módulo contratado, para el árbol de permisos finos
    secciones_por_modulo = {m['clave']: secciones_de_modulo(m['clave']) for m in modulos_empresa}

    return render(request, 'admon_usuarios/gestion_usuarios.html', {
        'empleados': empleados,
        'sucursales': sucursales,
        'grupos': grupos,
        'empresas_con_sucursales': empresas_con_sucursales,
        'accesos_por_usuario': accesos_por_usuario,
        'modulos_empresa': modulos_empresa,
        'modulos_por_usuario': modulos_por_usuario,
        'secciones_por_modulo': secciones_por_modulo,
        'ocultas_por_usuario': ocultas_por_usuario,
        'titulo_pagina': "Gestión de Personal"
    })

@login_required
def crear_usuario(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        nombre = request.POST.get('first_name')
        sucursales_ids = request.POST.getlist('sucursales')

        # 1. Validar si ya existe
        if User.objects.filter(username=username).exists():
            messages.error(request, f"El usuario {username} ya existe.")
            return redirect('gestion_usuarios')

        # 2. Crear objeto User
        nuevo_user = User.objects.create_user(
            username=username, 
            email=email, 
            password=username, 
            first_name=nombre
        )

        # 3. Configurar Perfil
        perfil = nuevo_user.perfil
        sucursales_ids = request.POST.getlist('sucursales')
        grupos_ids = request.POST.getlist('grupos')

        if sucursales_ids:
            perfil.sucursales.set(sucursales_ids)
            primera = Sucursal.objects.get(id=sucursales_ids[0])
            perfil.sucursal_defecto = primera
            # Derivar empresas de las sucursales seleccionadas
            from admon_empresas.models import Empresa
            empresas_ids = Sucursal.objects.filter(id__in=sucursales_ids).values_list('empresa_id', flat=True).distinct()
            perfil.empresas.set(empresas_ids)
            perfil.empresa_default = Empresa.objects.get(id=list(empresas_ids)[0])

        if grupos_ids:
            nuevo_user.groups.set(grupos_ids)

        perfil.save()

        # 3b. Módulos y secciones visibles (Capa 2 y 3) — igual que en editar.
        # Sin esto el usuario nace sin accesos y ve el menú vacío.
        from admon_empresas.models import AccesoModuloUsuario, SeccionOcultaUsuario
        from admon_empresas.modulos import secciones_de_modulo
        gestor = request.user.perfil
        empresa_gestor = gestor.empresa_default
        if empresa_gestor and (request.user.is_superuser or gestor.tipo_usuario == 'OWNER'):
            modulos_ids = request.POST.getlist('modulos')
            AccesoModuloUsuario.objects.filter(usuario=nuevo_user, empresa=empresa_gestor).delete()
            for clave in modulos_ids:
                AccesoModuloUsuario.objects.create(usuario=nuevo_user, empresa=empresa_gestor, modulo=clave)
            SeccionOcultaUsuario.objects.filter(usuario=nuevo_user, empresa=empresa_gestor).delete()
            visibles = set(request.POST.getlist('seccion_visible'))
            for clave_mod in modulos_ids:
                for s in secciones_de_modulo(clave_mod):
                    if s['clave'] not in visibles:
                        SeccionOcultaUsuario.objects.create(
                            usuario=nuevo_user, empresa=empresa_gestor, seccion=s['clave'])

        # 4. Enviar Invitación
        if enviar_correo_bienvenida(nuevo_user, request):
            messages.success(request, f"Usuario {username} creado exitosamente. Se ha enviado la invitación a {email}.")
        else:
            messages.warning(request, f"Usuario {username} creado, pero hubo un problema con el servidor de correo. Intenta reenviar la invitación más tarde.")

        return redirect('gestion_usuarios')
    
    return redirect('gestion_usuarios')

@login_required
def editar_usuario(request, usuario_id):
    empleado = get_object_or_404(User, id=usuario_id)
    
    if request.method == 'POST':
        # 1. Actualizar datos básicos
        empleado.email = request.POST.get('email')
        empleado.first_name = request.POST.get('first_name')
        empleado.save()
        
        # 2. Actualizar Accesos (ManyToMany)
        perfil = empleado.perfil
        sucursales_ids = request.POST.getlist('sucursales')
        grupos_ids = request.POST.getlist('grupos')

        perfil.sucursales.set(sucursales_ids)

        if sucursales_ids:
            if not perfil.sucursal_defecto or str(perfil.sucursal_defecto.id) not in sucursales_ids:
                perfil.sucursal_defecto = Sucursal.objects.get(id=sucursales_ids[0])
            # Sincronizar empresas desde sucursales seleccionadas
            from admon_empresas.models import Empresa
            empresas_ids = list(Sucursal.objects.filter(id__in=sucursales_ids).values_list('empresa_id', flat=True).distinct())
            perfil.empresas.set(empresas_ids)
            if not perfil.empresa_default or perfil.empresa_default.id not in empresas_ids:
                perfil.empresa_default = Empresa.objects.get(id=empresas_ids[0])
        else:
            perfil.sucursal_defecto = None
            perfil.empresa_default = None
            perfil.empresas.clear()

        if grupos_ids:
            empleado.groups.set(grupos_ids)

        perfil.save()

        # 3. Módulos visibles (Capa 2): sincronizar para la empresa del gestor
        from admon_empresas.models import AccesoModuloUsuario
        gestor = request.user.perfil
        empresa_gestor = gestor.empresa_default
        if empresa_gestor and (request.user.is_superuser or gestor.tipo_usuario == 'OWNER'):
            modulos_ids = request.POST.getlist('modulos')
            AccesoModuloUsuario.objects.filter(usuario=empleado, empresa=empresa_gestor).delete()
            for clave in modulos_ids:
                AccesoModuloUsuario.objects.create(usuario=empleado, empresa=empresa_gestor, modulo=clave)

            # Capa 3: secciones OCULTAS. Las pantallas marcadas (visibles) llegan en
            # 'seccion_visible'; ocultamos las que NO estén marcadas, de los módulos asignados.
            from admon_empresas.models import SeccionOcultaUsuario
            from admon_empresas.modulos import secciones_de_modulo
            SeccionOcultaUsuario.objects.filter(usuario=empleado, empresa=empresa_gestor).delete()
            visibles = set(request.POST.getlist('seccion_visible'))
            for clave_mod in modulos_ids:
                for s in secciones_de_modulo(clave_mod):
                    if s['clave'] not in visibles:
                        SeccionOcultaUsuario.objects.create(
                            usuario=empleado, empresa=empresa_gestor, seccion=s['clave'])

        messages.success(request, f"Los accesos de {empleado.username} han sido actualizados.")
        return redirect('gestion_usuarios')
    
    return redirect('gestion_usuarios')

@login_required
def reenviar_invitacion(request, usuario_id):
    """
    Reenvía el correo de bienvenida usando la lógica que ya validamos.
    """
    empleado = get_object_or_404(User, id=usuario_id)
    
    # Usamos la función que centraliza el envío
    if enviar_correo_bienvenida(empleado, request):
        messages.success(request, f"¡Invitación reenviada con éxito a {empleado.email}!")
    else:
        messages.error(request, "Error al enviar el correo. Revisa que las credenciales del .env sean correctas.")
        
    return redirect('gestion_usuarios')

@login_required
def toggle_activo_usuario(request, usuario_id):
    """Activa/desactiva el acceso de un usuario (is_active). Desactivado = no
    puede iniciar sesión; no se borra nada, es reversible. Solo dueño/superadmin."""
    if request.method != 'POST':
        return redirect('gestion_usuarios')
    gestor = getattr(request.user, 'perfil', None)
    if not (request.user.is_superuser or (gestor and gestor.tipo_usuario == 'OWNER')):
        messages.error(request, "No tienes permiso para desactivar usuarios.")
        return redirect('gestion_usuarios')
    empleado = get_object_or_404(User, id=usuario_id)
    if empleado.id == request.user.id:
        messages.error(request, "No puedes desactivar tu propia cuenta.")
        return redirect('gestion_usuarios')
    if empleado.is_superuser:
        messages.error(request, "No se puede desactivar a un superadministrador.")
        return redirect('gestion_usuarios')
    empleado.is_active = not empleado.is_active
    empleado.save(update_fields=['is_active'])
    if empleado.is_active:
        messages.success(request, f"{empleado.username} fue reactivado; ya puede iniciar sesión.")
    else:
        messages.success(request, f"{empleado.username} fue desactivado; ya no puede iniciar sesión.")
    return redirect('gestion_usuarios')


@login_required
def resetear_password_usuario(request, usuario_id):
    """El admin resetea la contraseña de un usuario que la olvidó: la deja en
    temporal (= su usuario) y lo obliga a crear una nueva al entrar. Reenvía el
    correo con las instrucciones. Solo dueño/superadmin."""
    if request.method != 'POST':
        return redirect('gestion_usuarios')
    gestor = getattr(request.user, 'perfil', None)
    if not (request.user.is_superuser or (gestor and gestor.tipo_usuario == 'OWNER')):
        messages.error(request, "No tienes permiso para resetear contraseñas.")
        return redirect('gestion_usuarios')
    empleado = get_object_or_404(User, id=usuario_id)
    if empleado.is_superuser and empleado.id != request.user.id:
        messages.error(request, "No se puede resetear la contraseña de un superadministrador.")
        return redirect('gestion_usuarios')

    # Contraseña temporal = su usuario (mismo patrón que el alta) y se le fuerza
    # a crear una nueva al iniciar sesión (invitacion_aceptada = False).
    empleado.set_password(empleado.username)
    empleado.save(update_fields=['password'])
    perfil = empleado.perfil
    perfil.invitacion_aceptada = False
    perfil.save(update_fields=['invitacion_aceptada'])

    enviado = enviar_correo_bienvenida(empleado, request) if empleado.email else False
    if enviado:
        messages.success(request, f"Contraseña de {empleado.username} reseteada. Se le envió el correo con su contraseña temporal (su mismo usuario) para que cree una nueva al entrar.")
    else:
        messages.warning(request, f"Contraseña de {empleado.username} reseteada. Su contraseña temporal es su usuario ('{empleado.username}'); al entrar deberá crear una nueva. No se pudo enviar el correo, avísale manualmente.")
    return redirect('gestion_usuarios')


@login_required
def mi_perfil(request):
    """Cada usuario edita su propio perfil: nombre, apellido, correo, foto y
    (opcional) su contraseña."""
    perfil = getattr(request.user, 'perfil', None)
    if request.method == 'POST':
        accion = request.POST.get('accion')
        if accion == 'perfil':
            request.user.first_name = (request.POST.get('first_name') or '').strip()
            request.user.last_name = (request.POST.get('last_name') or '').strip()
            request.user.email = (request.POST.get('email') or '').strip()
            request.user.save(update_fields=['first_name', 'last_name', 'email'])
            if perfil:
                perfil.nombre = request.user.first_name
                perfil.apellido = request.user.last_name
                if request.FILES.get('foto'):
                    perfil.foto = request.FILES['foto']
                perfil.save()
            messages.success(request, "Tu perfil fue actualizado.")
            return redirect('mi_perfil')
        elif accion == 'password':
            form = PasswordChangeForm(request.user, request.POST)
            if form.is_valid():
                user = form.save()
                update_session_auth_hash(request, user)  # no cerrar sesión
                messages.success(request, "Tu contraseña fue cambiada.")
                return redirect('mi_perfil')
            else:
                return render(request, 'admon_usuarios/mi_perfil.html', {
                    'perfil': perfil, 'password_form': form, 'seccion': None})

    return render(request, 'admon_usuarios/mi_perfil.html', {
        'perfil': perfil, 'password_form': PasswordChangeForm(request.user), 'seccion': None})


@login_required
def cambiar_password_obligatorio(request):
    # Usamos request.empresa (que viene del middleware) para el texto del template
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()

            # Marcamos la invitación como aceptada ANTES de cerrar sesión
            perfil = user.perfil
            perfil.invitacion_aceptada = True
            perfil.save()

            # Cerramos la sesión para que el usuario inicie con su nueva contraseña
            auth_logout(request)

            messages.success(request, "¡Cuenta activada con éxito! Inicia sesión con tu nueva contraseña.")
            return redirect('login')
        else:
            # Los errores de validación (ej. contraseñas no coinciden)
            # se manejan automáticamente en el form
            pass
    else:
        form = PasswordChangeForm(request.user)

    return render(request, 'admon_usuarios/cambiar_password.html', {
        'form': form,
        'empresa': request.empresa
    })