import decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.utils import timezone

from admon_inventarios.models import Producto, Ubicacion, Existencia, Lote
from admon_inventarios.views import _contexto_valido, puede_editar_maestro
from admon_inventarios.services import registrar_movimiento, StockInsuficiente
from .models import Receta, DetalleReceta, OrdenProduccion, ConsumoProduccion


class RecetasView(LoginRequiredMixin, View):
    """Catálogo de recetas/BOM. El maestro lo administra la matriz."""
    template_name = 'admon_produccion/recetas.html'

    def get(self, request):
        ctx = _contexto_valido(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx

        from admon_empresas import listas
        from django.urls import reverse
        res = listas.construir(
            request,
            Receta.objects.filter(empresa=empresa).select_related(
                'producto_terminado').prefetch_related('insumos__insumo').order_by('nombre'),
            placeholder='Receta, versión o producto terminado (SKU / nombre)',
            search_header=('nombre', 'version', 'producto_terminado__sku',
                           'producto_terminado__nombre'),
            clear_url=reverse('admon_produccion:recetas'),
            export_nombre='recetas',
            export_order=('nombre',),
            export_columnas=[
                ('Receta', 'nombre'), ('Versión', 'version'),
                ('Producto terminado', lambda o: str(o.producto_terminado) if o.producto_terminado else ''),
                ('Rendimiento', 'rendimiento'),
                ('Activa', lambda o: 'Sí' if o.activa else 'No')],
        )
        if res['export']:
            return res['export']
        context = {
            'recetas': res['page_obj'], 'page_obj': res['page_obj'],
            'totales': res['totales'], 'lista': res['lista'],
            'producibles': Producto.objects.filter(empresa=empresa, es_producible=True, activo=True),
            'materias_primas': Producto.objects.filter(empresa=empresa, es_materia_prima=True, activo=True),
            'puede_editar_maestro': puede_editar_maestro(request),
            'sucursal_activa': sucursal,
            'seccion': 'produccion',
        }
        return render(request, self.template_name, context)

    def post(self, request):
        ctx = _contexto_valido(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx

        if not puede_editar_maestro(request):
            messages.error(request, "Solo la sucursal matriz puede administrar recetas.")
            return redirect('admon_produccion:recetas')

        accion = request.POST.get('accion')

        if accion == 'crear_receta':
            producto = get_object_or_404(
                Producto, id=request.POST.get('producto_terminado'),
                empresa=empresa, es_producible=True)
            receta = Receta.objects.create(
                empresa=empresa,
                producto_terminado=producto,
                nombre=request.POST.get('nombre'),
                version=request.POST.get('version') or '1.0',
                rendimiento=decimal.Decimal(request.POST.get('rendimiento') or '1'),
                descripcion=request.POST.get('descripcion'),
            )
            insumo_ids = request.POST.getlist('insumo_id[]')
            cantidades = request.POST.getlist('cantidad_insumo[]')
            for i, iid in enumerate(insumo_ids):
                cant = decimal.Decimal(cantidades[i] or '0')
                if iid and cant > 0:
                    DetalleReceta.objects.create(
                        receta=receta,
                        insumo=get_object_or_404(Producto, id=iid, empresa=empresa),
                        cantidad_requerida=cant,
                    )
            messages.success(request, f"Receta '{receta.nombre}' creada.")

        elif accion == 'eliminar_receta':
            receta = get_object_or_404(Receta, id=request.POST.get('receta_id'), empresa=empresa)
            if receta.ordenproduccion_set.exists():
                receta.activa = False
                receta.save()
                messages.info(request, "La receta tiene órdenes asociadas: se desactivó en lugar de eliminarse.")
            else:
                receta.delete()
                messages.success(request, "Receta eliminada.")

        return redirect('admon_produccion:recetas')


class OrdenesProduccionView(LoginRequiredMixin, View):
    template_name = 'admon_produccion/ordenes_produccion.html'

    def get(self, request):
        ctx = _contexto_valido(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx

        from admon_empresas import listas
        from django.urls import reverse
        res = listas.construir(
            request,
            OrdenProduccion.objects.filter(empresa=empresa, sucursal=sucursal).select_related(
                'receta__producto_terminado', 'responsable'),
            placeholder='Folio, receta o producto terminado',
            search_header=('folio', 'receta__nombre',
                           'receta__producto_terminado__sku',
                           'receta__producto_terminado__nombre'),
            date_field='fecha_creacion',
            exactos={'estado': 'estado'},
            filtros_ui=[
                {'name': 'estado', 'label': 'Estado', 'tipo': 'select',
                 'opciones': OrdenProduccion.ESTADO_CHOICES},
                {'name': 'desde', 'label': 'Desde', 'tipo': 'date'},
                {'name': 'hasta', 'label': 'Hasta', 'tipo': 'date'},
            ],
            clear_url=reverse('admon_produccion:ordenes_produccion'),
            export_nombre='ordenes_produccion',
            export_order=('-fecha_creacion',),
            export_columnas=[
                ('Folio', 'folio'),
                ('Producto', lambda o: str(o.receta.producto_terminado) if o.receta and o.receta.producto_terminado else ''),
                ('A producir', 'cantidad_a_producir'), ('Producido', 'cantidad_producida'),
                ('Estado', 'get_estado_display'),
                ('Creada', lambda o: o.fecha_creacion.strftime('%d/%m/%Y') if o.fecha_creacion else '')],
        )
        if res['export']:
            return res['export']
        context = {
            'ordenes': res['page_obj'], 'page_obj': res['page_obj'],
            'totales': res['totales'], 'lista': res['lista'],
            'recetas': Receta.objects.filter(empresa=empresa, activa=True).select_related('producto_terminado'),
            'sucursal_activa': sucursal,
            'seccion': 'produccion',
        }
        return render(request, self.template_name, context)

    def post(self, request):
        """Crear orden de producción."""
        ctx = _contexto_valido(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx

        receta = get_object_or_404(Receta, id=request.POST.get('receta'), empresa=empresa, activa=True)
        cantidad = decimal.Decimal(request.POST.get('cantidad') or '0')
        if cantidad <= 0:
            messages.error(request, "La cantidad a producir debe ser mayor a 0.")
            return redirect('admon_produccion:ordenes_produccion')

        orden = OrdenProduccion.objects.create(
            empresa=empresa, sucursal=sucursal, receta=receta,
            cantidad_a_producir=cantidad, responsable=request.user,
            notas=request.POST.get('notas'),
        )
        messages.success(request, f"Orden {orden.folio} creada.")
        return redirect('admon_produccion:orden_produccion_detalle', pk=orden.pk)


class OrdenProduccionDetalleView(LoginRequiredMixin, View):
    template_name = 'admon_produccion/orden_produccion_detalle.html'

    def get(self, request, pk):
        ctx = _contexto_valido(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx

        orden = get_object_or_404(
            OrdenProduccion.objects.select_related('receta__producto_terminado', 'responsable'),
            pk=pk, empresa=empresa)

        factor = orden.cantidad_a_producir / orden.receta.rendimiento

        requerimientos = []
        for det in orden.receta.insumos.select_related('insumo'):
            requerido = det.cantidad_requerida * factor
            existencias = Existencia.objects.filter(
                producto=det.insumo, sucursal=sucursal, cantidad__gt=0,
            ).select_related('ubicacion', 'ubicacion__almacen', 'lote', 'serie')
            requerimientos.append({
                'detalle': det,
                'requerido': requerido,
                'existencias': existencias,
            })

        context = {
            'orden': orden,
            'requerimientos': requerimientos,
            'consumos': orden.consumos.select_related('insumo', 'lote', 'serie', 'ubicacion'),
            'ubicaciones': Ubicacion.objects.filter(
                almacen__sucursal=sucursal, activa=True).select_related('almacen'),
            'producto_final_loteable': orden.receta.producto_terminado.es_loteable,
            'sucursal_activa': sucursal,
            'seccion': 'produccion',
        }
        return render(request, self.template_name, context)

    @transaction.atomic
    def post(self, request, pk):
        ctx = _contexto_valido(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx

        orden = get_object_or_404(OrdenProduccion, pk=pk, empresa=empresa, sucursal=sucursal)
        accion = request.POST.get('accion')

        try:
            if accion == 'iniciar' and orden.estado == 'ABIERTA':
                orden.estado = 'EN_PROCESO'
                orden.fecha_inicio = timezone.now()
                orden.save()
                messages.success(request, f"{orden.folio} en proceso.")

            elif accion == 'cancelar' and orden.estado in ('ABIERTA', 'EN_PROCESO'):
                orden.estado = 'CANCELADA'
                orden.save()
                messages.info(request, f"{orden.folio} cancelada.")

            elif accion == 'completar' and orden.estado == 'EN_PROCESO':
                self._completar(request, empresa, sucursal, orden)
                messages.success(request, f"{orden.folio} completada: entró el producto terminado al inventario.")

            else:
                messages.error(request, "Acción no válida para el estado actual.")

        except (ValueError, StockInsuficiente) as e:
            transaction.set_rollback(True)
            messages.error(request, f"Error: {e}")

        return redirect('admon_produccion:orden_produccion_detalle', pk=pk)

    def _completar(self, request, empresa, sucursal, orden):
        """Consume los insumos capturados y da entrada al producto terminado."""
        # 1. Consumir insumos
        hubo_consumo = False
        for det in orden.receta.insumos.select_related('insumo'):
            exist_ids = request.POST.getlist(f'cons_exist_{det.id}[]')
            cants = request.POST.getlist(f'cons_cant_{det.id}[]')
            for j, ex_id in enumerate(exist_ids):
                cant = decimal.Decimal(cants[j] or '0')
                if not ex_id or cant <= 0:
                    continue
                existencia = get_object_or_404(
                    Existencia, id=ex_id, producto=det.insumo, sucursal=sucursal)
                registrar_movimiento(
                    empresa=empresa, sucursal=sucursal, producto=det.insumo,
                    ubicacion=existencia.ubicacion, tipo='PROD_CONSUMO', origen='PRODUCCION',
                    cantidad=cant, usuario=request.user,
                    lote=existencia.lote, serie=existencia.serie,
                    referencia=orden.folio,
                )
                ConsumoProduccion.objects.create(
                    orden=orden, insumo=det.insumo,
                    lote=existencia.lote, serie=existencia.serie,
                    ubicacion=existencia.ubicacion, cantidad_consumida=cant,
                )
                hubo_consumo = True

        if not hubo_consumo and orden.receta.insumos.exists():
            raise ValueError("No se capturó ningún consumo de insumos.")

        # 2. Entrada del producto terminado
        producto = orden.receta.producto_terminado
        ubi_id = request.POST.get('ubicacion_terminado')
        if not ubi_id:
            raise ValueError("Falta la ubicación destino del producto terminado.")
        ubicacion = get_object_or_404(Ubicacion, id=ubi_id, almacen__sucursal=sucursal)

        cantidad_real = decimal.Decimal(request.POST.get('cantidad_producida') or '0')
        if cantidad_real <= 0:
            raise ValueError("Captura la cantidad realmente producida.")

        lote_obj = None
        if producto.es_loteable:
            lote_num = request.POST.get('lote_terminado')
            if not lote_num:
                raise ValueError(f"El producto {producto.nombre} requiere lote de producción.")
            lote_obj, _ = Lote.objects.get_or_create(
                producto=producto, numero_lote=lote_num.strip(),
                defaults={
                    'fecha_fabricacion': timezone.now().date(),
                    'fecha_caducidad': request.POST.get('caducidad_terminado') or None,
                },
            )

        registrar_movimiento(
            empresa=empresa, sucursal=sucursal, producto=producto,
            ubicacion=ubicacion, tipo='PROD_ENTRADA', origen='PRODUCCION',
            cantidad=cantidad_real, usuario=request.user, lote=lote_obj,
            referencia=orden.folio,
        )

        orden.cantidad_producida = cantidad_real
        orden.estado = 'COMPLETADA'
        orden.fecha_fin = timezone.now()
        orden.save()
