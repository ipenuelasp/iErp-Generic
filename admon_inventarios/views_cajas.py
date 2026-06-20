"""Módulo de llenado de cajas (armado libre + consigna).

Una caja es un contenedor físico de stock que sale a cirugía. Se puede
armar libremente (sin plantilla Kit) eligiendo productos consumibles y/o
herramientas de renta. La primera carga es ágil: buscador + checkbox +
cantidad inline navegable con Tab/Enter.
"""
import decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin

from .models import (
    Producto, Ubicacion, Existencia, InstanciaKit, Consignante,
)
from .views import _contexto_valido
from .services import armar_caja, StockInsuficiente


class CajasView(LoginRequiredMixin, View):
    """Lista de cajas físicas de la sucursal + alta de caja nueva."""
    template_name = 'admon_inventarios/cajas.html'

    def get(self, request):
        ctx = _contexto_valido(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx

        cajas = InstanciaKit.objects.filter(
            empresa=empresa, sucursal_actual=sucursal
        ).exclude(estado='BAJA').select_related('kit', 'consignante').prefetch_related('lineas')

        # Resumen de contenido físico actual por caja
        for c in cajas:
            cont = list(c.contenido())
            c.num_productos = len(cont)
            c.total_piezas = sum((e.cantidad for e in cont), decimal.Decimal('0'))

        return render(request, self.template_name, {
            'cajas': cajas,
            'consignantes': Consignante.objects.filter(empresa=empresa, activo=True),
            'sucursal_activa': sucursal,
            'seccion': 'inventarios',
        })

    def post(self, request):
        ctx = _contexto_valido(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        accion = request.POST.get('accion') or 'crear'

        propiedad = request.POST.get('propiedad') or 'PROPIO'
        consignante = None
        if propiedad == 'CONSIGNA':
            consignante = get_object_or_404(
                Consignante, id=request.POST.get('consignante'), empresa=empresa)

        codigo = (request.POST.get('codigo_caja') or '').strip()
        if not codigo:
            messages.error(request, "La caja necesita un código.")
            return redirect('admon_inventarios:cajas')

        # Edición de una caja existente
        if accion == 'editar':
            caja = get_object_or_404(InstanciaKit, id=request.POST.get('caja_id'), empresa=empresa)
            if InstanciaKit.objects.filter(empresa=empresa, codigo_caja=codigo).exclude(id=caja.id).exists():
                messages.error(request, f"Ya existe otra caja con el código {codigo}.")
                return redirect('admon_inventarios:cajas')
            caja.codigo_caja = codigo
            caja.nombre = request.POST.get('nombre') or codigo
            caja.propiedad = propiedad
            caja.consignante = consignante
            caja.notas = request.POST.get('notas')
            # Al editar una caja, se vuelve 100% libre: copia la receta del kit
            # (si la tenía y aún no tiene receta propia) y se desliga de la plantilla.
            if caja.kit_id and not caja.lineas.exists():
                from .models import ContenidoCaja
                for comp in caja.kit.componentes.select_related('producto'):
                    ContenidoCaja.objects.get_or_create(
                        caja=caja, producto=comp.producto,
                        defaults={'cantidad_objetivo': comp.cantidad_requerida,
                                  'es_retornable': comp.es_retornable})
            caja.kit = None
            caja.save()
            messages.success(request, f"Caja {caja.codigo_caja} actualizada.")
            return redirect('admon_inventarios:cajas')

        if InstanciaKit.objects.filter(empresa=empresa, codigo_caja=codigo).exists():
            messages.error(request, f"Ya existe una caja con el código {codigo}.")
            return redirect('admon_inventarios:cajas')

        caja = InstanciaKit.objects.create(
            empresa=empresa,
            kit=None,
            nombre=request.POST.get('nombre') or codigo,
            codigo_caja=codigo,
            sucursal_actual=sucursal,
            propiedad=propiedad,
            consignante=consignante,
            notas=request.POST.get('notas'),
        )
        messages.success(request, f"Caja {caja.codigo_caja} creada. Ahora arma su contenido.")
        return redirect('admon_inventarios:armar_caja', pk=caja.pk)


class ArmarCajaView(LoginRequiredMixin, View):
    """Llenado rápido de una caja: define la receta y mete el stock físico."""
    template_name = 'admon_inventarios/armar_caja.html'

    def get(self, request, pk):
        ctx = _contexto_valido(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        caja = get_object_or_404(InstanciaKit, id=pk, empresa=empresa)

        # Receta actual (lo ya definido) para precargar
        import json
        actuales = {l.producto_id: l for l in caja.lineas.all()}
        actuales_json = json.dumps({
            str(pid): {'cant': float(l.cantidad_objetivo), 'ret': l.es_retornable}
            for pid, l in actuales.items()
        })

        productos = Producto.objects.filter(empresa=empresa, activo=True).order_by('nombre')

        return render(request, self.template_name, {
            'caja': caja,
            'productos': productos,
            'actuales': actuales,
            'actuales_json': actuales_json,
            'es_consigna': caja.propiedad == 'CONSIGNA',
            'sucursal_activa': sucursal,
            'seccion': 'inventarios',
        })

    def post(self, request, pk):
        ctx = _contexto_valido(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        caja = get_object_or_404(InstanciaKit, id=pk, empresa=empresa)

        if caja.estado not in ('DISPONIBLE', 'EN_PREPARACION', 'REABASTECIENDO'):
            messages.error(request, "Solo puedes armar cajas disponibles o en preparación.")
            return redirect('admon_inventarios:cajas')

        prod_ids = request.POST.getlist('producto_id[]')
        cants = request.POST.getlist('cantidad[]')
        retornables = request.POST.getlist('es_retornable[]')  # valores = producto_id marcados

        lineas = []
        for i, pid in enumerate(prod_ids):
            cant = cants[i] if i < len(cants) else '0'
            lineas.append({
                'producto_id': pid,
                'cantidad': cant,
                'es_retornable': pid in retornables,
            })

        if not any(decimal.Decimal(l['cantidad'] or 0) > 0 for l in lineas):
            messages.error(request, "Captura al menos un producto con cantidad.")
            return redirect('admon_inventarios:armar_caja', pk=pk)

        # Armar = solo definir la receta (borrador de la caja). El inventario
        # NO se toca aquí; eso pasa al reabastecer.
        try:
            n = armar_caja(caja=caja, lineas=lineas, origen_ubicacion=None,
                           usuario=request.user, mover_stock=False)
        except (ValueError, StockInsuficiente) as e:
            messages.error(request, f"Error al armar la caja: {e}")
            return redirect('admon_inventarios:armar_caja', pk=pk)

        messages.success(request, f"Caja {caja.codigo_caja} definida ({n} productos). Reabastécela para cargar el material.")
        return redirect('admon_inventarios:cajas')
