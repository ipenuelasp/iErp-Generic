from django import forms
from .models import Empresa, Moneda, Sucursal

# forms.py
class EmpresaForm(forms.ModelForm):
    class Meta:
        model = Empresa
        fields = ['nombre_fiscal', 'rfc', 'moneda_principal', 'color_primario', 'tema_error', 'email_contador', 'logo', 'isotipo']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Si estamos editando una empresa existente
        if self.instance and self.instance.pk:
            # Filtramos para que solo aparezcan las monedas de ESTA empresa
            self.fields['moneda_principal'].queryset = Moneda.objects.filter(empresa=self.instance)
            self.fields['moneda_principal'].empty_label = "Selecciona una moneda..."
        
class SucursalForm(forms.ModelForm):
    # Definimos la variable fuera para que no marque error
    clase_css = "mt-1 block w-full border-slate-200 rounded-xl shadow-sm focus:ring-2 focus:ring-indigo-500 p-3 bg-slate-50"
    
    nombre = forms.CharField(
        widget=forms.TextInput(attrs={'class': clase_css, 'placeholder': 'Ej. Sucursal Norte'})
    )
    codigo_sucursal = forms.CharField(
        widget=forms.TextInput(attrs={'class': clase_css, 'placeholder': 'SUC-002'})
    )

    class Meta:
        model = Sucursal
        fields = ['nombre', 'codigo_sucursal']