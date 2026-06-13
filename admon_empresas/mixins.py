from django.db import models
from .models import Sucursal, Empresa
from django.contrib.auth.mixins import UserPassesTestMixin
from django.shortcuts import redirect
from django.contrib import messages


class StaffRequiredMixin(UserPassesTestMixin):
    """Acceso solo si pertenece a los grupos Staff o Dueños"""
    def test_func(self):
        # Verificamos si el usuario pertenece a alguno de estos nombres de grupo
        grupos_permitidos = ['Dueños', 'Administradores']
        return self.request.user.groups.filter(name__in=grupos_permitidos).exists() or self.request.user.is_superuser

    def handle_no_permission(self):
        messages.error(self.request, "Tu perfil no tiene los permisos de grupo necesarios.")
        return redirect('home')
    
class TenantModel(models.Model):
    """ Clase abstracta para heredar en todos los modelos de negocio """
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT)
    sucursal = models.ForeignKey(Sucursal, on_delete=models.PROTECT)

    class Meta:
        abstract = True

class GroupRequiredMixin(UserPassesTestMixin):
    """Permite definir qué grupos pueden entrar a cada vista.

    Acepta tanto grupos de Django como tipo_usuario del perfil,
    para que usuarios OWNER/MANAGER funcionen sin necesitar grupos asignados.
    """
    group_required = None  # Lo definiremos en cada vista

    # Mapa de equivalencia: grupo Django → tipos de usuario permitidos
    _GRUPO_A_TIPO = {
        'Dueños':          ['OWNER'],
        'Administradores': ['OWNER', 'MANAGER'],
        'Gerentes':        ['MANAGER'],
    }

    def test_func(self):
        if self.request.user.is_superuser:
            return True

        if self.group_required is None:
            return False  # Sin grupos definidos, nadie pasa

        # 1. Verificar grupos Django (método clásico)
        if self.request.user.groups.filter(name__in=self.group_required).exists():
            return True

        # 2. Verificar tipo_usuario del perfil como alternativa
        try:
            tipo = self.request.user.perfil.tipo_usuario
            tipos_permitidos = []
            for grupo in self.group_required:
                tipos_permitidos.extend(self._GRUPO_A_TIPO.get(grupo, []))
            return tipo in tipos_permitidos
        except Exception:
            return False

    def handle_no_permission(self):
        messages.error(self.request, "No tienes el rol necesario para acceder a esta sección.")
        return redirect('home')