from django import forms
from .models import Proveedor, AutorizadorCompra
from admon_empresas.models import Sucursal, Moneda


INPUT_CLS = ('w-full bg-slate-50 border border-slate-200 rounded-xl p-3 text-xs '
             'font-bold text-slate-700 focus:ring-2 focus:ring-brand transition-all')


class ProveedorForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop('empresa', None)
        super().__init__(*args, **kwargs)

        for name, field in self.fields.items():
            if name == 'sucursales_acceso':
                continue
            field.widget.attrs.update({'class': INPUT_CLS})

        if empresa:
            self.fields['sucursales_acceso'].queryset = Sucursal.objects.filter(empresa=empresa)
            self.fields['moneda_predeterminada'].queryset = Moneda.objects.filter(empresa=empresa)

    class Meta:
        model = Proveedor
        fields = [
            'nombre_fiscal', 'nombre_comercial', 'rfc', 'email',
            'telefono', 'celular', 'direccion', 'contacto_nombre',
            'moneda_predeterminada', 'dias_credito', 'sucursales_acceso',
        ]
        widgets = {
            'sucursales_acceso': forms.CheckboxSelectMultiple(),
        }


class AutorizadorCompraForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop('empresa', None)
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': INPUT_CLS})

        if empresa:
            from admon_empresas.models import PerfilUsuario
            from django.contrib.auth.models import User
            # Usuarios que pertenecen a esta empresa
            qs = User.objects.filter(perfil__empresas=empresa).distinct()
            self.fields['usuario'].queryset = qs
            self.fields['supervisor'].queryset = qs
            self.fields['supervisor'].required = False
            self.fields['supervisor'].empty_label = "— Sin supervisor (cima de la cadena) —"

    class Meta:
        model = AutorizadorCompra
        fields = ['usuario', 'monto_autorizado', 'supervisor']
