from django import forms
from .models import Cliente
from admon_empresas.models import Sucursal, Moneda


INPUT_CLS = ('w-full bg-slate-50 border border-slate-200 rounded-xl p-3 text-xs '
             'font-bold text-slate-700 focus:ring-2 focus:ring-brand transition-all')


class ClienteForm(forms.ModelForm):
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
        model = Cliente
        fields = [
            'nombre_fiscal', 'nombre_comercial', 'rfc', 'email',
            'telefono', 'contacto_nombre', 'direccion', 'codigo_postal',
            'regimen_fiscal', 'moneda_predeterminada',
            'dias_credito', 'limite_credito', 'constancia_fiscal', 'sucursales_acceso',
        ]
        widgets = {
            'sucursales_acceso': forms.CheckboxSelectMultiple(),
            'constancia_fiscal': forms.ClearableFileInput(attrs={'accept': 'application/pdf'}),
        }
