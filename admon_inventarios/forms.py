from django import forms
from .models import Almacen, Clase, Grupo, Tipo, Producto, Ubicacion, UnidadMedida


class EstiloBaseForm(forms.ModelForm):
    """Aplica el estilo del sistema y absorbe kwargs de contexto (empresa/sucursal)."""
    def __init__(self, *args, **kwargs):
        self.sucursal = kwargs.pop('sucursal', None)
        self.empresa = kwargs.pop('empresa', None)
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({'class': 'w-5 h-5 rounded border-slate-300 text-brand focus:ring-brand'})
            else:
                field.widget.attrs.update({
                    'class': 'w-full bg-slate-50 border-none rounded-xl p-3 text-xs font-bold text-slate-700 focus:ring-2 focus:ring-brand transition-all mb-4'
                })


class ClaseForm(EstiloBaseForm):
    class Meta:
        model = Clase
        fields = ['codigo', 'descripcion']


class GrupoForm(EstiloBaseForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.sucursal and 'ubicacion_defecto' in self.fields:
            self.fields['ubicacion_defecto'].queryset = Ubicacion.objects.filter(
                almacen__sucursal=self.sucursal
            )

    class Meta:
        model = Grupo
        fields = ['codigo', 'descripcion', 'es_inventariable', 'ubicacion_defecto']


class TipoForm(EstiloBaseForm):
    class Meta:
        model = Tipo
        fields = ['codigo', 'descripcion']


class UnidadMedidaForm(EstiloBaseForm):
    class Meta:
        model = UnidadMedida
        fields = ['codigo', 'descripcion']


class ProductoForm(EstiloBaseForm):
    class Meta:
        model = Producto
        fields = [
            'clase', 'grupo', 'tipo', 'nombre', 'sku', 'descripcion',
            'codigo_barras', 'alcance', 'impuesto',
            'es_loteable', 'es_serializable',
            'es_comprable', 'es_vendible', 'es_materia_prima', 'es_producible', 'es_retornable',
            'registro_sanitario',
            'costo_unitario', 'precio_venta', 'margen', 'activo', 'unidad_medida',
            'ubicacion_defecto',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for f in ('costo_unitario', 'precio_venta', 'margen', 'clase', 'grupo', 'tipo',
                  'codigo_barras', 'registro_sanitario', 'descripcion', 'impuesto'):
            self.fields[f].required = False

        self.fields['clase'].empty_label = "--- Sin Clase ---"
        self.fields['grupo'].empty_label = "--- Sin Grupo ---"
        self.fields['tipo'].empty_label = "--- Sin Tipo ---"
        self.fields['impuesto'].empty_label = "--- Usar impuesto por defecto ---"

        if self.empresa:
            self.fields['clase'].queryset = Clase.objects.filter(empresa=self.empresa)
            self.fields['grupo'].queryset = Grupo.objects.filter(empresa=self.empresa)
            self.fields['tipo'].queryset = Tipo.objects.filter(empresa=self.empresa)
            self.fields['unidad_medida'].queryset = UnidadMedida.objects.filter(empresa=self.empresa)
            from admon_empresas.models import Impuesto
            self.fields['impuesto'].queryset = Impuesto.objects.filter(empresa=self.empresa, activo=True)

        if self.sucursal:
            self.fields['ubicacion_defecto'].queryset = Ubicacion.objects.filter(
                almacen__sucursal=self.sucursal
            )


class AlmacenForm(EstiloBaseForm):
    class Meta:
        model = Almacen
        fields = ['codigo', 'nombre', 'direccion', 'es_uso_personal']
        widgets = {
            'direccion': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Dirección física del almacén...'}),
        }


class UbicacionForm(EstiloBaseForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.sucursal:
            self.fields['almacen'].queryset = Almacen.objects.filter(sucursal=self.sucursal)

    class Meta:
        model = Ubicacion
        fields = ['almacen', 'codigo', 'descripcion']
