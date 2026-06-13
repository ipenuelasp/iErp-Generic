from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline, StackedInline
from .models import ClienteSaaS, Empresa, Sucursal

from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User


from .models import ClienteSaaS, Empresa, Sucursal, PerfilUsuario

class SucursalInline(TabularInline):
    model = Sucursal
    extra = 0 # No mostrar filas vacías por defecto
    fields = ("nombre", "codigo_sucursal", "es_matriz")

@admin.register(ClienteSaaS)
class ClienteSaaSAdmin(ModelAdmin):
    list_display = ('nombre_comercial', 'slug_instancia', 'fecha_registro')
    search_fields = ('nombre_comercial',)

@admin.register(Empresa)
class EmpresaAdmin(ModelAdmin):
    list_display = ("nombre_fiscal", "rfc", "cliente", "total_sucursales")
    search_fields = ("nombre_fiscal", "rfc", "cliente__nombre_comercial")
    list_filter = ("cliente",)
    inlines = [SucursalInline]

    # Columna calculada para ver cuántas sucursales tiene cada empresa
    def total_sucursales(self, obj):
        return obj.sucursales.count()
    total_sucursales.short_description = "N° Sucursales"

@admin.register(Sucursal)
class SucursalAdmin(ModelAdmin):
    # Aquí es donde verás a qué empresa pertenece cada sucursal
    list_display = ("nombre", "empresa", "codigo_sucursal", "es_matriz")    
    list_filter = ("empresa", "es_matriz")
    search_fields = ("nombre", "codigo_sucursal", "empresa__nombre_fiscal")
    
    # Esto hace que al editar una sucursal, el selector de empresa sea más elegante
    autocomplete_fields = ["empresa"]

# Quitamos el registro por defecto de User para poner el nuestro
admin.site.unregister(User)


class PerfilUsuarioInline(admin.StackedInline):
    model = PerfilUsuario
    can_delete = False
    verbose_name_plural = 'Perfil de Usuario'
    # Añadimos 'puede_gestionar_usuarios' al final de la lista
    fields = (
        'nombre', 
        'apellido', 
        'tipo_usuario', 
        'puede_gestionar_usuarios',
        'empresas', 
        'empresa_default', 
        'sucursal_defecto'
    )
    # Como empresas es ManyToMany, puedes usar esto para que se vea mejor:
    filter_horizontal = ('empresas',)

@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin): # Heredamos de Unfold
    inlines = (PerfilUsuarioInline,)
    # Aquí puedes agregar estilos de Unfold para que se vea más limpio