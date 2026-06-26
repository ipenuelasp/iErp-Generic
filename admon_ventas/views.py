import decimal
from datetime import datetime

from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from admon_empresas.models import Moneda, Impuesto
from admon_inventarios.models import Producto, Existencia
from admon_inventarios.models import SalidaKit
from .models import Cliente, Pedido, DetallePedido, Cotizacion, DetalleCotizacion
from .forms import ClienteForm
from . import services
from . import import_clientes
from django.http import HttpResponse


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _contexto(request):
    if not request.empresa:
        messages.warning(request, "No hay una empresa activa.")
        return None
    if not request.sucursal_activa:
        messages.warning(request, "No hay una sucursal activa. Selecciona una sede arriba.")
        return None
    return request.empresa, request.sucursal_activa


def _kits_visible(request, empresa):
    """La liquidación de salidas aplica a empresas con Kits pero SIN el módulo
    de Cirugías (en Insermed la liquidación vive dentro de Cirugías)."""
    from admon_empresas.modulos import modulos_visibles
    mods = modulos_visibles(request.user, empresa)
    return 'kits' in mods and 'cirugias' not in mods


def _cirugias_visible(request, empresa):
    from admon_empresas.modulos import modulos_visibles
    return 'cirugias' in modulos_visibles(request.user, empresa)


def clientes_visibles(empresa, sucursal):
    return Cliente.objects.filter(empresa=empresa, activo=True).filter(
        Q(sucursales_acceso=sucursal) | Q(sucursales_acceso__isnull=True)
    ).distinct()


def _puede_ver_costos(request):
    """Costo/ganancia del pedido solo lo ve el dueño / superusuario."""
    if request.user.is_superuser:
        return True
    perfil = getattr(request.user, 'perfil', None)
    return bool(perfil and perfil.tipo_usuario == 'OWNER')


def productos_para_pedido(empresa, sucursal):
    """Productos vendibles con su existencia en la sucursal, para el selector del
    pedido. Ordena primero lo disponible (con stock o servicio), luego lo agotado."""
    from django.db.models import Sum
    prods = list(Producto.objects.filter(
        empresa=empresa, activo=True, es_vendible=True).select_related('grupo').order_by('nombre'))
    stock = {r['producto']: r['s'] for r in Existencia.objects.filter(
        producto__empresa=empresa, ubicacion__almacen__sucursal=sucursal
    ).values('producto').annotate(s=Sum('cantidad'))}
    for p in prods:
        p.stock_actual = stock.get(p.id, 0) or 0
    # Disponible primero (con stock o servicio no inventariable), luego por nombre
    prods.sort(key=lambda p: (0 if (p.stock_actual > 0 or p.es_servicio) else 1, p.nombre.lower()))
    return prods


def _aplicar_partidas(pedido, empresa, request):
    """Reescribe las partidas del pedido y recalcula totales con el catálogo
    de impuestos. Traslados suman, retenciones restan."""
    productos_ids = request.POST.getlist('producto[]')
    cantidades = request.POST.getlist('cantidad[]')
    precios = request.POST.getlist('precio[]')
    margenes = request.POST.getlist('margen[]')
    impuestos_ids = request.POST.getlist('impuesto[]')

    default_imp = Impuesto.objects.filter(empresa=empresa, es_default=True).first()

    pedido.detalles.all().delete()
    subtotal = decimal.Decimal('0')
    imp_total = decimal.Decimal('0')

    for i, pid in enumerate(productos_ids):
        if not pid or not cantidades[i]:
            continue
        cant = decimal.Decimal(cantidades[i] or '0')
        prec = decimal.Decimal(precios[i] or '0')
        margen_val = margenes[i] if i < len(margenes) else ''
        try:
            margen = decimal.Decimal(margen_val) if margen_val not in ('', None) else None
        except decimal.InvalidOperation:
            margen = None
        imp_id = impuestos_ids[i] if i < len(impuestos_ids) else ''
        imp = Impuesto.objects.filter(id=imp_id, empresa=empresa).first() if imp_id else default_imp
        tasa = imp.tasa if imp else decimal.Decimal('0')
        es_ret = imp.es_retencion if imp else False

        sub = cant * prec
        monto = sub * (tasa / 100)
        DetallePedido.objects.create(
            pedido=pedido, producto_id=pid, cantidad=cant,
            precio_unitario=prec, margen=margen, impuesto=imp,
            iva_porcentaje=tasa, es_retencion=es_ret)
        subtotal += sub
        imp_total += (-monto if es_ret else monto)

    pedido.subtotal = subtotal
    pedido.impuestos = imp_total
    pedido.total = subtotal + imp_total
    pedido.save()


# --------------------------------------------------------------------------
# CLIENTES
# --------------------------------------------------------------------------
class ClientesView(LoginRequiredMixin, View):
    template_name = 'admon_ventas/clientes.html'

    def get(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        from admon_empresas import listas
        from django.urls import reverse
        qs = Cliente.objects.filter(empresa=empresa).prefetch_related(
            'sucursales_acceso').order_by('nombre_fiscal')
        res = listas.construir(
            request, qs,
            placeholder='Nombre, RFC, email o contacto',
            search_header=('nombre_fiscal', 'nombre_comercial', 'rfc',
                           'email', 'contacto_nombre'),
            exactos={'activo': 'activo'},
            filtros_ui=[
                {'name': 'activo', 'label': 'Estatus', 'tipo': 'select', 'todos': 'Todos',
                 'opciones': [('1', 'Activos'), ('0', 'Inactivos')]},
            ],
            clear_url=reverse('admon_ventas:clientes'),
            export_nombre='clientes',
            export_order=('nombre_fiscal',),
            export_columnas=[
                ('Razón social', 'nombre_fiscal'), ('Comercial', 'nombre_comercial'),
                ('RFC', 'rfc'), ('Email', 'email'), ('Contacto', 'contacto_nombre'),
                ('Activo', lambda o: 'Sí' if o.activo else 'No')],
        )
        if res['export']:
            return res['export']
        context = {
            'clientes': res['page_obj'], 'page_obj': res['page_obj'],
            'totales': res['totales'], 'lista': res['lista'],
            'form': ClienteForm(empresa=empresa),
            'sucursal_activa': sucursal,
            'seccion': 'ventas',
        }
        return render(request, self.template_name, context)

    def post(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx

        action = request.POST.get('action')
        if action == 'delete':
            cli = get_object_or_404(Cliente, id=request.POST.get('item_id'), empresa=empresa)
            try:
                cli.delete()
                messages.success(request, "Cliente eliminado.")
            except Exception:
                cli.activo = False
                cli.save()
                messages.info(request, "El cliente tiene pedidos asociados: se desactivó.")
            return redirect('admon_ventas:clientes')

        item_id = request.POST.get('item_id')
        instance = Cliente.objects.filter(id=item_id, empresa=empresa).first() if item_id else None
        form = ClienteForm(request.POST, request.FILES, instance=instance, empresa=empresa)
        if form.is_valid():
            cli = form.save(commit=False)
            cli.empresa = empresa
            cli.save()
            form.save_m2m()
            messages.success(request, "Cliente guardado correctamente.")
        else:
            messages.error(request, f"Error en el formulario: {form.errors.as_text()}")
        return redirect('admon_ventas:clientes')


class LeerConstanciaView(LoginRequiredMixin, View):
    """Lee una CSF (PDF) y devuelve los datos extraídos en JSON para
    autocompletar el formulario. No guarda nada: solo lee."""
    def post(self, request):
        from django.http import JsonResponse
        from .csf import parse_csf
        archivo = request.FILES.get('constancia')
        if not archivo:
            return JsonResponse({'ok': False, 'error': 'No se recibió archivo.'}, status=400)
        if not archivo.name.lower().endswith('.pdf'):
            return JsonResponse({'ok': False, 'error': 'El archivo debe ser PDF.'}, status=400)
        try:
            datos = parse_csf(archivo)
        except Exception as e:
            return JsonResponse({'ok': False, 'error': f'No se pudo leer el PDF: {e}'}, status=200)
        return JsonResponse(datos, status=200)


class DescargarPlantillaClientesView(LoginRequiredMixin, View):
    """Plantilla .xlsx de clientes (con ejemplo). Solo superuser."""
    def get(self, request):
        if not request.user.is_superuser:
            messages.error(request, "Solo el administrador puede descargar la plantilla.")
            return redirect('admon_ventas:clientes')
        contenido = import_clientes.generar_plantilla(con_ejemplo=True)
        resp = HttpResponse(
            contenido,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        resp['Content-Disposition'] = 'attachment; filename="plantilla_clientes.xlsx"'
        return resp


class ImportarClientesView(LoginRequiredMixin, View):
    """Carga masiva de clientes desde Excel. Solo superuser."""
    def post(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        if not request.user.is_superuser:
            messages.error(request, "Solo el administrador puede hacer carga masiva.")
            return redirect('admon_ventas:clientes')
        archivo = request.FILES.get('archivo')
        if not archivo or not archivo.name.lower().endswith('.xlsx'):
            messages.error(request, "Selecciona un archivo .xlsx (Excel).")
            return redirect('admon_ventas:clientes')
        try:
            res = import_clientes.importar(archivo, empresa)
        except Exception as e:
            messages.error(request, f"No se pudo procesar el archivo: {e}")
            return redirect('admon_ventas:clientes')
        messages.success(
            request, f"Carga masiva: {res['creados']} nuevos, {res['actualizados']} actualizados.")
        for err in res['errores'][:10]:
            messages.warning(request, err)
        return redirect('admon_ventas:clientes')


# --------------------------------------------------------------------------
# PEDIDOS
# --------------------------------------------------------------------------
class NuevoPedidoView(LoginRequiredMixin, View):
    template_name = 'admon_ventas/pedido_form.html'

    def get(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        context = {
            'clientes': clientes_visibles(empresa, sucursal),
            'productos': productos_para_pedido(empresa, sucursal),
            'puede_ver_costos': _puede_ver_costos(request),
            'monedas': Moneda.objects.filter(empresa=empresa, activa=True),
            'impuestos': Impuesto.objects.filter(empresa=empresa, activo=True),
            'sucursal_activa': sucursal,
            'seccion': 'ventas',
        }
        return render(request, self.template_name, context)

    @transaction.atomic
    def post(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx

        if not any(request.POST.getlist('producto[]')):
            messages.error(request, "El pedido debe tener al menos una partida.")
            return redirect('admon_ventas:nuevo_pedido')

        ultimo = Pedido.objects.filter(
            empresa=empresa, sucursal=sucursal).order_by('consecutivo').last()
        consecutivo = (ultimo.consecutivo + 1) if ultimo else 1
        anio = datetime.now().strftime('%y')
        folio = f"{sucursal.codigo_sucursal or 'PED'}-V{anio}-{consecutivo:05d}"

        pedido = Pedido.objects.create(
            empresa=empresa, sucursal=sucursal,
            cliente_id=request.POST.get('cliente'),
            moneda_id=request.POST.get('moneda'),
            folio=folio, consecutivo=consecutivo,
            fecha_entrega_estimada=request.POST.get('fecha_entrega') or None,
            genera_cxc=bool(request.POST.get('genera_cxc')),
            notas=request.POST.get('notas', ''),
            estado='BORRADOR', creado_por=request.user,
        )
        _aplicar_partidas(pedido, empresa, request)
        messages.success(request, f"Pedido {pedido.folio} creado como borrador.")
        return redirect('admon_ventas:pedido_detalle', pk=pedido.pk)


class EditarPedidoView(LoginRequiredMixin, View):
    template_name = 'admon_ventas/pedido_form.html'

    def get(self, request, pk):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        pedido = get_object_or_404(Pedido, id=pk, empresa=empresa)
        if pedido.estado != 'BORRADOR':
            messages.error(request, "Este pedido ya no se puede editar.")
            return redirect('admon_ventas:pedido_detalle', pk=pk)
        context = {
            'pedido': pedido,
            'detalles': pedido.detalles.select_related('producto'),
            'clientes': clientes_visibles(empresa, sucursal),
            'productos': productos_para_pedido(empresa, sucursal),
            'puede_ver_costos': _puede_ver_costos(request),
            'monedas': Moneda.objects.filter(empresa=empresa, activa=True),
            'impuestos': Impuesto.objects.filter(empresa=empresa, activo=True),
            'sucursal_activa': sucursal,
            'seccion': 'ventas',
        }
        return render(request, self.template_name, context)

    @transaction.atomic
    def post(self, request, pk):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        pedido = get_object_or_404(Pedido, id=pk, empresa=empresa)
        if pedido.estado != 'BORRADOR':
            messages.error(request, "Este pedido ya no se puede editar.")
            return redirect('admon_ventas:pedido_detalle', pk=pk)

        pedido.cliente_id = request.POST.get('cliente')
        pedido.moneda_id = request.POST.get('moneda')
        pedido.notas = request.POST.get('notas', '')
        pedido.fecha_entrega_estimada = request.POST.get('fecha_entrega') or None
        pedido.genera_cxc = bool(request.POST.get('genera_cxc'))
        pedido.save()

        _aplicar_partidas(pedido, empresa, request)
        messages.success(request, f"Pedido {pedido.folio} actualizado.")
        return redirect('admon_ventas:pedido_detalle', pk=pedido.pk)


class HistorialPedidosView(LoginRequiredMixin, View):
    template_name = 'admon_ventas/historial_pedidos.html'

    def get(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        from admon_empresas import listas
        from django.urls import reverse
        qs = Pedido.objects.filter(
            empresa=empresa, sucursal=sucursal
        ).select_related('cliente', 'moneda', 'creado_por').prefetch_related('detalles__producto')

        res = listas.construir(
            request, qs,
            placeholder='Folio, cliente, notas o producto (SKU / nombre) del detalle',
            search_header=('folio', 'cliente__nombre_fiscal',
                           'cliente__nombre_comercial', 'notas'),
            detail_model=DetallePedido,
            detail_search=('producto__sku', 'producto__nombre'),
            date_field='fecha_emision',
            exactos={'estado': 'estado', 'cliente': 'cliente_id'},
            filtros_ui=[
                {'name': 'estado', 'label': 'Estado', 'tipo': 'select',
                 'opciones': Pedido.ESTADO_CHOICES},
                {'name': 'cliente', 'label': 'Cliente', 'tipo': 'select',
                 'opciones': [(c.id, str(c)) for c in
                              Cliente.objects.filter(empresa=empresa).order_by('nombre_fiscal')]},
                {'name': 'desde', 'label': 'Desde', 'tipo': 'date'},
                {'name': 'hasta', 'label': 'Hasta', 'tipo': 'date'},
            ],
            sum_fields=('subtotal', 'impuestos', 'total'),
            clear_url=reverse('admon_ventas:historial_pedidos'),
            export_nombre='pedidos',
            export_order=('-fecha_emision', '-id'),
            export_columnas=[
                ('Folio', 'folio'), ('Cliente', lambda o: str(o.cliente)),
                ('Estado', 'get_estado_display'),
                ('Fecha', lambda o: o.fecha_emision.strftime('%d/%m/%Y') if o.fecha_emision else ''),
                ('Subtotal', 'subtotal'), ('Impuestos', 'impuestos'),
                ('Total', 'total'), ('Moneda', lambda o: o.moneda.codigo if o.moneda else '')],
        )
        if res['export']:
            return res['export']
        context = {
            'pedidos': res['page_obj'], 'page_obj': res['page_obj'],
            'totales': res['totales'], 'lista': res['lista'],
            'sucursal_activa': sucursal, 'seccion': 'ventas',
        }
        return render(request, self.template_name, context)


class PedidoDetalleView(LoginRequiredMixin, View):
    template_name = 'admon_ventas/pedido_detalle.html'

    def get(self, request, pk):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        pedido = get_object_or_404(
            Pedido.objects.select_related('cliente', 'moneda', 'creado_por'),
            id=pk, empresa=empresa)
        cxc_cobrada = any(f.total_pagado > 0 for f in pedido.facturas.all()) if hasattr(pedido, 'facturas') else False
        detalles = list(pedido.detalles.select_related('producto', 'producto__unidad_medida'))
        # Ganancia del pedido (interno): venta sin IVA − costo
        venta_neta = sum((d.cantidad * d.precio_unitario for d in detalles), decimal.Decimal('0'))
        costo_total = sum((d.cantidad * (d.producto.costo_unitario or 0) for d in detalles), decimal.Decimal('0'))
        ganancia = venta_neta - costo_total
        ganancia_info = {
            'costo': costo_total, 'venta_neta': venta_neta, 'ganancia': ganancia,
            'margen': (ganancia / venta_neta * 100) if venta_neta else decimal.Decimal('0'),
        }
        context = {
            'pedido': pedido,
            'detalles': detalles,
            'ganancia': ganancia_info,
            'comisiones': pedido.comisiones.all(),
            'facturas': pedido.facturas.select_related('moneda') if hasattr(pedido, 'facturas') else [],
            'productos': productos_para_pedido(empresa, sucursal),
            'puede_ver_costos': _puede_ver_costos(request),
            'puede_entregar': pedido.estado in ('CONFIRMADO', 'ENTREGADO_PARCIAL'),
            # Extras/comisiones se editan mientras el pedido no esté cancelado ni la CxC cobrada
            'puede_editar_extras': pedido.estado != 'CANCELADO' and not cxc_cobrada,
            'sucursal_activa': sucursal,
            'seccion': 'ventas',
        }
        return render(request, self.template_name, context)

    def post(self, request, pk):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        pedido = get_object_or_404(Pedido, id=pk, empresa=empresa)
        accion = request.POST.get('accion')

        cxc_cobrada = any(f.total_pagado > 0 for f in pedido.facturas.all()) if hasattr(pedido, 'facturas') else False
        bloqueado = pedido.estado == 'CANCELADO' or cxc_cobrada

        if accion == 'add_extra':
            if bloqueado:
                messages.error(request, "El pedido está cerrado: no se pueden agregar extras.")
                return redirect('admon_ventas:pedido_detalle', pk=pk)
            prod = Producto.objects.filter(id=request.POST.get('producto'), empresa=empresa).first()
            cant = decimal.Decimal(request.POST.get('cantidad') or '0')
            precio = decimal.Decimal(request.POST.get('precio') or (prod.precio_venta if prod else 0))
            if not prod or cant <= 0:
                messages.error(request, "Selecciona producto y cantidad.")
                return redirect('admon_ventas:pedido_detalle', pk=pk)
            imp = prod.impuesto or Impuesto.objects.filter(empresa=empresa, es_default=True).first()
            DetallePedido.objects.create(
                pedido=pedido, producto=prod, tipo_linea=DetallePedido.LINEA_PRODUCTO,
                cantidad=cant, cantidad_entregada=cant, precio_unitario=precio,
                impuesto=imp, iva_porcentaje=(imp.tasa if imp else 0),
                es_retencion=(imp.es_retencion if imp else False), es_extra=True)
            services.recalcular_pedido(pedido)
            messages.success(request, f"Extra agregado: {prod.sku}.")
        elif accion == 'del_extra':
            d = pedido.detalles.filter(id=request.POST.get('detalle_id'), es_extra=True).first()
            if d and not bloqueado:
                d.delete(); services.recalcular_pedido(pedido)
                messages.info(request, "Extra eliminado.")
        elif accion == 'add_comision':
            ben = (request.POST.get('beneficiario') or '').strip()
            monto = decimal.Decimal(request.POST.get('monto') or '0')
            if ben and monto > 0:
                from .models import ComisionPedido
                ComisionPedido.objects.create(
                    pedido=pedido, tipo=request.POST.get('tipo') or 'TECNICO',
                    beneficiario=ben, monto=monto)
                messages.success(request, "Comisión agregada.")
            else:
                messages.error(request, "Captura beneficiario y monto.")
        elif accion == 'del_comision':
            pedido.comisiones.filter(id=request.POST.get('comision_id')).delete()
            messages.info(request, "Comisión eliminada.")
        elif accion == 'confirmar' and pedido.estado == 'BORRADOR':
            if not pedido.detalles.exists():
                messages.error(request, "El pedido no tiene partidas.")
            else:
                pedido.estado = 'CONFIRMADO'
                pedido.save(update_fields=['estado'])
                messages.success(request, f"{pedido.folio} confirmado. Listo para entregar.")
        elif accion == 'cancelar' and pedido.estado in ('BORRADOR', 'CONFIRMADO'):
            pedido.estado = 'CANCELADO'
            pedido.fecha_cancelacion = timezone.now()
            pedido.motivo_cancelacion = request.POST.get('motivo')
            pedido.save()
            messages.info(request, f"{pedido.folio} cancelado.")
        elif accion == 'cancelar_revertir':
            # Cancelar una venta ya entregada: regresa stock y cancela sus CxC.
            # Solo dueño/superusuario (afecta inventario y cuentas por cobrar).
            if not _puede_ver_costos(request):
                messages.error(request, "Solo el dueño puede cancelar ventas entregadas.")
                return redirect('admon_ventas:pedido_detalle', pk=pk)
            if pedido.estado not in ('ENTREGADO', 'ENTREGADO_PARCIAL'):
                messages.error(request, "Esta acción es solo para pedidos ya entregados.")
                return redirect('admon_ventas:pedido_detalle', pk=pk)
            from admon_inventarios.models import MovimientoInventario
            from admon_inventarios.services import registrar_movimiento, StockInsuficiente
            from admon_finanzas.models import FacturaCliente
            # Bloqueo: si alguna CxC ya tiene cobro, no se puede cancelar limpio
            cxcs = list(FacturaCliente.objects.filter(empresa=empresa, pedido=pedido).exclude(estado='CANCELADA'))
            if any(f.total_pagado > 0 for f in cxcs):
                messages.error(request, "No se puede cancelar: hay cobros aplicados. Primero reversa el cobro.")
                return redirect('admon_ventas:pedido_detalle', pk=pk)
            facturadas = [f.folio for f in cxcs if f.esta_facturada]
            with transaction.atomic():
                revertidos = 0
                movs = MovimientoInventario.objects.filter(
                    empresa=empresa, referencia=pedido.folio, tipo='VENTA')
                for m in movs:
                    registrar_movimiento(
                        empresa=empresa, sucursal=m.sucursal, producto=m.producto,
                        ubicacion=m.ubicacion, tipo='AJUSTE_POS', origen='AJUSTE',
                        cantidad=m.cantidad, usuario=request.user, lote=m.lote, serie=m.serie,
                        referencia=f"CANCEL {pedido.folio}", costo_unitario=m.costo_unitario,
                        propiedad=m.propiedad, consignante=m.consignante)
                    revertidos += 1
                for f in cxcs:
                    f.estado = 'CANCELADA'
                    f.save(update_fields=['estado'])
                pedido.detalles.update(cantidad_entregada=0)
                pedido.estado = 'CANCELADO'
                pedido.fecha_cancelacion = timezone.now()
                pedido.motivo_cancelacion = request.POST.get('motivo') or 'Cancelación con reversa'
                pedido.save(update_fields=['estado', 'fecha_cancelacion', 'motivo_cancelacion'])
            msg = f"{pedido.folio} cancelado: {revertidos} línea(s) regresadas a inventario y {len(cxcs)} CxC cancelada(s)."
            if facturadas:
                msg += f" OJO: {', '.join(facturadas)} ya tenía CFDI — cancela el timbre en el SAT con tu contador."
            messages.warning(request, msg)
        else:
            messages.error(request, "Acción no válida para el estado actual.")
        return redirect('admon_ventas:pedido_detalle', pk=pk)


class PedidoPDFView(LoginRequiredMixin, View):
    """PDF del pedido para el cliente. NO incluye comisiones internas ni costos."""
    def get(self, request, pk):
        if not request.empresa:
            return redirect('home')
        import io
        from django.template.loader import get_template
        from django.http import HttpResponse
        pedido = get_object_or_404(
            Pedido.objects.select_related('cliente', 'moneda', 'sucursal'), id=pk, empresa=request.empresa)
        html = get_template('admon_ventas/pedido_pdf.html').render({
            'pedido': pedido,
            'empresa': request.empresa,
            'detalles': pedido.detalles.select_related('producto'),
        })
        from xhtml2pdf import pisa
        result = io.BytesIO()
        pdf = pisa.pisaDocument(io.BytesIO(html.encode('UTF-8')), result)
        if pdf.err:
            return HttpResponse("Error al generar el PDF", status=400)
        resp = HttpResponse(result.getvalue(), content_type='application/pdf')
        resp['Content-Disposition'] = f'inline; filename="Pedido-{pedido.folio}.pdf"'
        return resp


class EntregaPedidoView(LoginRequiredMixin, View):
    template_name = 'admon_ventas/entrega.html'

    def get(self, request, pk):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        pedido = get_object_or_404(Pedido, id=pk, empresa=empresa)
        if pedido.estado not in ('CONFIRMADO', 'ENTREGADO_PARCIAL'):
            messages.error(request, "El pedido debe estar confirmado para entregarse.")
            return redirect('admon_ventas:pedido_detalle', pk=pk)

        # Existencias disponibles en la sucursal por cada partida pendiente
        detalles = list(pedido.detalles.select_related('producto', 'producto__unidad_medida'))
        for det in detalles:
            det.existencias_disp = Existencia.objects.filter(
                producto=det.producto, sucursal=sucursal, cantidad__gt=0
            ).select_related('ubicacion', 'ubicacion__almacen', 'lote', 'serie')

        context = {
            'pedido': pedido,
            'detalles': detalles,
            'sucursal_activa': sucursal,
            'seccion': 'ventas',
        }
        return render(request, self.template_name, context)

    def post(self, request, pk):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        pedido = get_object_or_404(Pedido, id=pk, empresa=empresa)

        try:
            resultado = services.entregar_pedido(pedido=pedido, request=request)
        except (services.ErrorVenta, ValueError) as e:
            messages.error(request, str(e))
            return redirect('admon_ventas:entrega_pedido', pk=pk)
        except Exception as e:
            messages.error(request, f"No se pudo procesar la entrega: {e}")
            return redirect('admon_ventas:entrega_pedido', pk=pk)

        if resultado.get('factura'):
            messages.success(
                request, f"Entrega registrada. Se generó la cuenta por cobrar {resultado['factura'].folio}.")
        else:
            messages.success(request, "Entrega registrada.")

        for sol in resultado.get('reabastos', []):
            messages.info(
                request, f"Reabasto automático: solicitud {sol.folio} a la matriz por stock bajo mínimo.")

        return redirect('admon_ventas:pedido_detalle', pk=pk)


# --------------------------------------------------------------------------
# CIRUGÍAS POR FACTURAR (puente cirugías → pedido, lado ventas)
# --------------------------------------------------------------------------
class CirugiasPorFacturarView(LoginRequiredMixin, View):
    """Lista de cirugías finalizadas por almacén, pendientes de generar pedido/CxC.
    Solo visible para empresas con módulo de Cirugías."""
    template_name = 'admon_ventas/cirugias_por_facturar.html'

    def get(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        if not _cirugias_visible(request, empresa):
            messages.warning(request, "Esta empresa no usa el módulo de Cirugías.")
            return redirect('admon_ventas:historial_pedidos')
        from admon_cirugias.models import SolicitudCirugia
        cirugias = SolicitudCirugia.objects.filter(
            empresa=empresa, estado='POR_FACTURAR'
        ).select_related('doctor', 'hospital', 'cliente').prefetch_related('salidas__contenido__producto')
        return render(request, self.template_name, {
            'cirugias': cirugias,
            'monedas': Moneda.objects.filter(empresa=empresa, activa=True),
            'sucursal_activa': sucursal, 'seccion': 'ventas',
        })


class GenerarPedidoCirugiaView(LoginRequiredMixin, View):
    """Ventas: genera el pedido + CxC desde una cirugía por facturar."""
    def post(self, request, pk):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        from admon_cirugias.models import SolicitudCirugia
        from admon_cirugias import services as cir_services
        sol = get_object_or_404(SolicitudCirugia, pk=pk, empresa=empresa)
        moneda = Moneda.objects.filter(id=request.POST.get('moneda'), empresa=empresa).first() \
            or empresa.moneda_principal
        try:
            pedido = cir_services.generar_pedido_de_cirugia(
                solicitud=sol, moneda=moneda, usuario=request.user)
        except cir_services.ErrorLiquidacion as e:
            messages.error(request, str(e))
            return redirect('admon_ventas:cirugias_por_facturar')
        messages.success(request, f"Pedido {pedido.folio} generado desde la cirugía {sol.folio}. Agrega extras/comisiones si aplica.")
        return redirect('admon_ventas:pedido_detalle', pk=pedido.pk)


# --------------------------------------------------------------------------
# COTIZACIONES
# --------------------------------------------------------------------------
def _aplicar_partidas_cot(cotizacion, empresa, request):
    productos_ids = request.POST.getlist('producto[]')
    cantidades = request.POST.getlist('cantidad[]')
    precios = request.POST.getlist('precio[]')
    impuestos_ids = request.POST.getlist('impuesto[]')
    tipos = request.POST.getlist('tipo_linea[]')

    default_imp = Impuesto.objects.filter(empresa=empresa, es_default=True).first()
    cotizacion.detalles.all().delete()
    subtotal = decimal.Decimal('0')
    imp_total = decimal.Decimal('0')

    for i, pid in enumerate(productos_ids):
        if not pid or not cantidades[i]:
            continue
        cant = decimal.Decimal(cantidades[i] or '0')
        prec = decimal.Decimal(precios[i] or '0')
        imp_id = impuestos_ids[i] if i < len(impuestos_ids) else ''
        imp = Impuesto.objects.filter(id=imp_id, empresa=empresa).first() if imp_id else default_imp
        tasa = imp.tasa if imp else decimal.Decimal('0')
        es_ret = imp.es_retencion if imp else False
        tipo = tipos[i] if i < len(tipos) else 'PRODUCTO'

        sub = cant * prec
        monto = sub * (tasa / 100)
        DetalleCotizacion.objects.create(
            cotizacion=cotizacion, producto_id=pid, tipo_linea=tipo, cantidad=cant,
            precio_unitario=prec, impuesto=imp, iva_porcentaje=tasa, es_retencion=es_ret)
        subtotal += sub
        imp_total += (-monto if es_ret else monto)

    cotizacion.subtotal = subtotal
    cotizacion.impuestos = imp_total
    cotizacion.total = subtotal + imp_total
    cotizacion.save()


class HistorialCotizacionesView(LoginRequiredMixin, View):
    template_name = 'admon_ventas/historial_cotizaciones.html'

    def get(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        from admon_empresas import listas
        from django.urls import reverse
        qs = Cotizacion.objects.filter(
            empresa=empresa, sucursal=sucursal).select_related('cliente', 'moneda')
        res = listas.construir(
            request, qs,
            placeholder='Folio, cliente, notas o producto (SKU / nombre) del detalle',
            search_header=('folio', 'cliente__nombre_fiscal',
                           'cliente__nombre_comercial', 'notas'),
            detail_model=DetalleCotizacion,
            detail_search=('producto__sku', 'producto__nombre'),
            date_field='fecha_emision',
            exactos={'estado': 'estado', 'cliente': 'cliente_id'},
            filtros_ui=[
                {'name': 'estado', 'label': 'Estado', 'tipo': 'select',
                 'opciones': Cotizacion.ESTADO_CHOICES},
                {'name': 'cliente', 'label': 'Cliente', 'tipo': 'select',
                 'opciones': [(c.id, str(c)) for c in
                              Cliente.objects.filter(empresa=empresa).order_by('nombre_fiscal')]},
                {'name': 'desde', 'label': 'Desde', 'tipo': 'date'},
                {'name': 'hasta', 'label': 'Hasta', 'tipo': 'date'},
            ],
            sum_fields=('subtotal', 'impuestos', 'total'),
            clear_url=reverse('admon_ventas:historial_cotizaciones'),
            export_nombre='cotizaciones',
            export_order=('-fecha_emision', '-id'),
            export_columnas=[
                ('Folio', 'folio'), ('Cliente', lambda o: str(o.cliente)),
                ('Estado', 'get_estado_display'),
                ('Fecha', lambda o: o.fecha_emision.strftime('%d/%m/%Y') if o.fecha_emision else ''),
                ('Subtotal', 'subtotal'), ('Impuestos', 'impuestos'),
                ('Total', 'total'), ('Moneda', lambda o: o.moneda.codigo if o.moneda else '')],
        )
        if res['export']:
            return res['export']
        context = {
            'cotizaciones': res['page_obj'], 'page_obj': res['page_obj'],
            'totales': res['totales'], 'lista': res['lista'],
            'sucursal_activa': sucursal, 'seccion': 'ventas',
        }
        return render(request, self.template_name, context)


class NuevaCotizacionView(LoginRequiredMixin, View):
    template_name = 'admon_ventas/cotizacion_form.html'

    def _form_ctx(self, request, empresa, sucursal, cot=None):
        return {
            'cotizacion': cot,
            'detalles': cot.detalles.select_related('producto') if cot else None,
            'clientes': clientes_visibles(empresa, sucursal),
            'productos': productos_para_pedido(empresa, sucursal),
            'puede_ver_costos': _puede_ver_costos(request),
            'monedas': Moneda.objects.filter(empresa=empresa, activa=True),
            'impuestos': Impuesto.objects.filter(empresa=empresa, activo=True),
            'sucursal_activa': sucursal,
            'seccion': 'ventas',
        }

    def get(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        return render(request, self.template_name, self._form_ctx(request, empresa, sucursal))

    @transaction.atomic
    def post(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        if not any(request.POST.getlist('producto[]')):
            messages.error(request, "La cotización debe tener al menos una partida.")
            return redirect('admon_ventas:nueva_cotizacion')

        ultimo = Cotizacion.objects.filter(empresa=empresa, sucursal=sucursal).order_by('consecutivo').last()
        consecutivo = (ultimo.consecutivo + 1) if ultimo else 1
        folio = f"{sucursal.codigo_sucursal or 'COT'}-C{datetime.now().strftime('%y')}-{consecutivo:05d}"

        cot = Cotizacion.objects.create(
            empresa=empresa, sucursal=sucursal, cliente_id=request.POST.get('cliente'),
            moneda_id=request.POST.get('moneda'), folio=folio, consecutivo=consecutivo,
            vigencia=request.POST.get('vigencia') or None, notas=request.POST.get('notas', ''),
            estado='BORRADOR', creado_por=request.user)
        _aplicar_partidas_cot(cot, empresa, request)
        messages.success(request, f"Cotización {cot.folio} creada.")
        return redirect('admon_ventas:cotizacion_detalle', pk=cot.pk)


class CotizacionPDFView(LoginRequiredMixin, View):
    def get(self, request, pk):
        if not request.empresa:
            return redirect('home')
        import io
        from django.template.loader import get_template
        cot = get_object_or_404(
            Cotizacion.objects.select_related('cliente', 'moneda', 'sucursal'), id=pk, empresa=request.empresa)
        html = get_template('admon_ventas/cotizacion_pdf.html').render({
            'cotizacion': cot, 'empresa': request.empresa,
            'detalles': cot.detalles.select_related('producto'),
        })
        from xhtml2pdf import pisa
        result = io.BytesIO()
        pdf = pisa.pisaDocument(io.BytesIO(html.encode('UTF-8')), result)
        if pdf.err:
            return HttpResponse("Error al generar el PDF", status=400)
        resp = HttpResponse(result.getvalue(), content_type='application/pdf')
        resp['Content-Disposition'] = f'inline; filename="Cotizacion-{cot.folio}.pdf"'
        return resp


class EditarCotizacionView(NuevaCotizacionView):
    def get(self, request, pk):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        cot = get_object_or_404(Cotizacion, id=pk, empresa=empresa)
        if cot.estado not in ('BORRADOR', 'ENVIADA'):
            messages.error(request, "Esta cotización ya no se puede editar.")
            return redirect('admon_ventas:cotizacion_detalle', pk=pk)
        return render(request, self.template_name, self._form_ctx(request, empresa, sucursal, cot))

    @transaction.atomic
    def post(self, request, pk):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        cot = get_object_or_404(Cotizacion, id=pk, empresa=empresa)
        if cot.estado not in ('BORRADOR', 'ENVIADA'):
            messages.error(request, "Esta cotización ya no se puede editar.")
            return redirect('admon_ventas:cotizacion_detalle', pk=pk)
        cot.cliente_id = request.POST.get('cliente')
        cot.moneda_id = request.POST.get('moneda')
        cot.vigencia = request.POST.get('vigencia') or None
        cot.notas = request.POST.get('notas', '')
        cot.save()
        _aplicar_partidas_cot(cot, empresa, request)
        messages.success(request, f"Cotización {cot.folio} actualizada.")
        return redirect('admon_ventas:cotizacion_detalle', pk=cot.pk)


class CotizacionDetalleView(LoginRequiredMixin, View):
    template_name = 'admon_ventas/cotizacion_detalle.html'

    def get(self, request, pk):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        cot = get_object_or_404(
            Cotizacion.objects.select_related('cliente', 'moneda', 'pedido_generado'), id=pk, empresa=empresa)
        context = {
            'cotizacion': cot,
            'detalles': cot.detalles.select_related('producto', 'producto__unidad_medida'),
            'sucursal_activa': sucursal,
            'seccion': 'ventas',
        }
        return render(request, self.template_name, context)

    def post(self, request, pk):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        cot = get_object_or_404(Cotizacion, id=pk, empresa=empresa)
        accion = request.POST.get('accion')

        if accion == 'enviar' and cot.estado == 'BORRADOR':
            cot.estado = 'ENVIADA'; cot.save(update_fields=['estado'])
            messages.success(request, f"{cot.folio} marcada como enviada.")
        elif accion == 'aceptar' and cot.estado in ('ENVIADA', 'BORRADOR'):
            cot.estado = 'ACEPTADA'; cot.save(update_fields=['estado'])
            messages.success(request, f"{cot.folio} aceptada. Ya puedes convertirla en pedido.")
        elif accion == 'rechazar' and cot.estado in ('ENVIADA', 'BORRADOR'):
            cot.estado = 'RECHAZADA'; cot.save(update_fields=['estado'])
            messages.info(request, f"{cot.folio} rechazada.")
        elif accion == 'convertir' and cot.estado in ('ACEPTADA', 'ENVIADA'):
            try:
                pedido = services.convertir_cotizacion(cotizacion=cot, usuario=request.user)
                messages.success(request, f"Pedido {pedido.folio} creado desde {cot.folio}.")
                return redirect('admon_ventas:pedido_detalle', pk=pedido.pk)
            except services.ErrorVenta as e:
                messages.error(request, str(e))
        else:
            messages.error(request, "Acción no válida para el estado actual.")
        return redirect('admon_ventas:cotizacion_detalle', pk=pk)


# --------------------------------------------------------------------------
# LIQUIDACIÓN DE CIRUGÍA / KIT  →  PEDIDO
# --------------------------------------------------------------------------
class LiquidacionesView(LoginRequiredMixin, View):
    template_name = 'admon_ventas/liquidaciones.html'

    def get(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        if not _kits_visible(request, empresa):
            messages.info(request, "Las cirugías se liquidan desde el módulo de Cirugías.")
            return redirect('admon_ventas:historial_pedidos')
        salidas = SalidaKit.objects.filter(
            empresa=empresa, sucursal_origen=sucursal, estado='RETORNADA', pedido_generado__isnull=True
        ).select_related('instancia_kit__kit')
        context = {
            'salidas': salidas,
            'sucursal_activa': sucursal,
            'seccion': 'ventas',
        }
        return render(request, self.template_name, context)


class LiquidarSalidaView(LoginRequiredMixin, View):
    template_name = 'admon_ventas/liquidar_salida.html'

    def get(self, request, salida_id):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        if not _kits_visible(request, empresa):
            messages.info(request, "Las cirugías se liquidan desde el módulo de Cirugías.")
            return redirect('admon_ventas:historial_pedidos')
        salida = get_object_or_404(
            SalidaKit.objects.select_related('instancia_kit__kit', 'cliente'),
            id=salida_id, empresa=empresa)
        context = {
            'salida': salida,
            'contenido': salida.contenido.select_related('producto'),
            'clientes': clientes_visibles(empresa, sucursal),
            'monedas': Moneda.objects.filter(empresa=empresa, activa=True),
            'sucursal_activa': sucursal,
            'seccion': 'ventas',
        }
        return render(request, self.template_name, context)

    def post(self, request, salida_id):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        salida = get_object_or_404(SalidaKit, id=salida_id, empresa=empresa)

        cliente = Cliente.objects.filter(id=request.POST.get('cliente'), empresa=empresa).first()
        moneda = Moneda.objects.filter(id=request.POST.get('moneda'), empresa=empresa).first()

        comisiones = []
        tipos = request.POST.getlist('com_tipo[]')
        benes = request.POST.getlist('com_beneficiario[]')
        montos = request.POST.getlist('com_monto[]')
        for i, b in enumerate(benes):
            if b and i < len(montos) and montos[i]:
                comisiones.append({'tipo': tipos[i] if i < len(tipos) else 'TECNICO',
                                   'beneficiario': b, 'monto': montos[i]})

        try:
            res = services.liquidar_salida_kit(
                salida=salida, cliente=cliente, moneda=moneda,
                comisiones=comisiones, usuario=request.user)
        except services.ErrorVenta as e:
            messages.error(request, str(e))
            return redirect('admon_ventas:liquidar_salida', salida_id=salida_id)

        msg = f"Cirugía {salida.folio} liquidada: pedido {res['pedido'].folio}"
        if res.get('factura'):
            msg += f" y CxC {res['factura'].folio}"
        messages.success(request, msg + ".")
        return redirect('admon_ventas:pedido_detalle', pk=res['pedido'].pk)
