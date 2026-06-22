import decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse
from django.views import View
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Sum

from admon_empresas.models import Moneda
from admon_compras.models import OrdenCompra, Proveedor
from .models import FacturaProveedor, FacturaCliente, Pago, AplicacionPago, MetodoPago
from . import services


def _contexto(request):
    if not request.empresa:
        messages.warning(request, "No hay una empresa activa.")
        return None
    if not request.sucursal_activa:
        messages.warning(request, "No hay una sucursal activa. Selecciona una sede arriba.")
        return None
    return request.empresa, request.sucursal_activa


# --------------------------------------------------------------------------
# CUENTAS POR PAGAR
# --------------------------------------------------------------------------
class CuentasPorPagarView(LoginRequiredMixin, View):
    template_name = 'admon_finanzas/cuentas_por_pagar.html'

    def get(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        from admon_empresas import listas
        from django.urls import reverse
        from admon_compras.models import Proveedor

        qs = FacturaProveedor.objects.filter(empresa=empresa).select_related(
            'proveedor', 'moneda', 'orden_compra').prefetch_related('aplicaciones')

        res = listas.construir(
            request, qs,
            placeholder='Folio, UUID, proveedor o notas',
            search_header=('folio', 'uuid_cfdi', 'proveedor__nombre_fiscal',
                           'proveedor__nombre_comercial', 'notas'),
            date_field='fecha_emision',
            exactos={'estado': 'estado', 'proveedor': 'proveedor_id'},
            filtros_ui=[
                {'name': 'estado', 'label': 'Estado', 'tipo': 'select',
                 'opciones': FacturaProveedor.ESTADO_CHOICES},
                {'name': 'proveedor', 'label': 'Proveedor', 'tipo': 'select',
                 'opciones': [(p.id, str(p)) for p in
                              Proveedor.objects.filter(empresa=empresa).order_by('nombre_fiscal')]},
                {'name': 'desde', 'label': 'Desde', 'tipo': 'date'},
                {'name': 'hasta', 'label': 'Hasta', 'tipo': 'date'},
            ],
            sum_fields=('subtotal', 'impuestos', 'total'),
            clear_url=reverse('admon_finanzas:cuentas_por_pagar'),
            export_nombre='cuentas_por_pagar',
            export_order=('-fecha_emision', '-id'),
            export_columnas=[
                ('Folio', 'folio'), ('Proveedor', lambda o: str(o.proveedor)),
                ('UUID', 'uuid_cfdi'), ('Estado', 'get_estado_display'),
                ('Emisión', lambda o: o.fecha_emision.strftime('%d/%m/%Y') if o.fecha_emision else ''),
                ('Total', 'total'), ('Saldo', lambda o: o.saldo),
                ('Moneda', lambda o: o.moneda.codigo if o.moneda else '')],
        )
        if res['export']:
            return res['export']

        # Totales por pagar sobre el resultado filtrado (puede haber varias monedas)
        por_pagar = {}
        for f in res['qs']:
            if f.estado in ('PENDIENTE', 'PARCIAL'):
                cod = f.moneda.codigo
                por_pagar[cod] = por_pagar.get(cod, decimal.Decimal('0')) + f.saldo

        context = {
            'facturas': res['page_obj'], 'page_obj': res['page_obj'],
            'totales': res['totales'], 'lista': res['lista'],
            'resumen_por_pagar': por_pagar,
            'sucursal_activa': sucursal,
            'seccion': 'finanzas',
        }
        return render(request, self.template_name, context)


class RegistrarFacturaView(LoginRequiredMixin, View):
    """Registra una factura del proveedor contra una OC (puede haber varias)."""
    template_name = 'admon_finanzas/factura_form.html'

    def get(self, request, oc_id):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        orden = get_object_or_404(
            OrdenCompra.objects.select_related('proveedor', 'moneda'),
            id=oc_id, empresa=empresa)

        if orden.estado not in ('AUTORIZADO', 'RECIBIDO', 'FINALIZADO'):
            messages.error(request, "Solo se factura sobre órdenes autorizadas.")
            return redirect('admon_compras:orden_detalle', pk=oc_id)

        facturado = orden.facturas.exclude(estado='CANCELADA').aggregate(s=Sum('total'))['s'] or decimal.Decimal('0')

        context = {
            'orden': orden,
            'ya_facturado': facturado,
            'saldo_oc': orden.total - facturado,
            'sucursal_activa': sucursal,
            'seccion': 'finanzas',
        }
        return render(request, self.template_name, context)

    @transaction.atomic
    def post(self, request, oc_id):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        orden = get_object_or_404(OrdenCompra, id=oc_id, empresa=empresa)

        subtotal = decimal.Decimal(request.POST.get('subtotal') or '0')
        impuestos = decimal.Decimal(request.POST.get('impuestos') or '0')
        total = decimal.Decimal(request.POST.get('total') or '0')
        if total <= 0:
            messages.error(request, "El total de la factura debe ser mayor a 0.")
            return redirect('admon_finanzas:registrar_factura', oc_id=oc_id)

        FacturaProveedor.objects.create(
            empresa=empresa,
            orden_compra=orden,
            proveedor=orden.proveedor,
            folio=request.POST.get('folio'),
            uuid_cfdi=request.POST.get('uuid') or None,
            fecha_emision=request.POST.get('fecha_emision'),
            fecha_vencimiento=request.POST.get('fecha_vencimiento') or None,
            moneda=orden.moneda,
            subtotal=subtotal or total,
            impuestos=impuestos,
            total=total,
            notas=request.POST.get('notas'),
            archivo_xml=request.FILES.get('archivo_xml'),
            archivo_pdf=request.FILES.get('archivo_pdf'),
            registrada_por=request.user,
        )
        messages.success(request, f"Factura {request.POST.get('folio')} registrada para {orden.folio}.")
        return redirect('admon_compras:orden_detalle', pk=oc_id)


class FacturaDetalleView(LoginRequiredMixin, View):
    template_name = 'admon_finanzas/factura_detalle.html'

    def get(self, request, pk):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        factura = get_object_or_404(
            FacturaProveedor.objects.select_related('proveedor', 'moneda', 'orden_compra'),
            pk=pk, empresa=empresa)
        context = {
            'factura': factura,
            'aplicaciones': factura.aplicaciones.select_related('pago', 'pago__metodo'),
            'sucursal_activa': sucursal,
            'seccion': 'finanzas',
        }
        return render(request, self.template_name, context)

    def post(self, request, pk):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        factura = get_object_or_404(FacturaProveedor, pk=pk, empresa=empresa)
        if request.POST.get('accion') == 'cancelar' and factura.total_pagado == 0:
            factura.estado = 'CANCELADA'
            factura.save(update_fields=['estado'])
            messages.info(request, f"Factura {factura.folio} cancelada.")
        else:
            messages.error(request, "No se puede cancelar una factura con pagos aplicados.")
        return redirect('admon_finanzas:factura_detalle', pk=pk)


# --------------------------------------------------------------------------
# PAGOS
# --------------------------------------------------------------------------
class RegistrarPagoView(LoginRequiredMixin, View):
    template_name = 'admon_finanzas/pago_form.html'

    def get(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx

        facturas = services.facturas_por_pagar(empresa)
        context = {
            'facturas': facturas,
            'metodos': MetodoPago.objects.filter(empresa=empresa, activo=True),
            'monedas': Moneda.objects.filter(empresa=empresa, activa=True),
            'moneda_base': empresa.moneda_principal,
            'sucursal_activa': sucursal,
            'seccion': 'finanzas',
        }
        return render(request, self.template_name, context)

    def post(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx

        factura_ids = request.POST.getlist('factura_id[]')
        montos = request.POST.getlist('monto_aplicado[]')
        tipos_cambio = request.POST.getlist('tipo_cambio[]')

        aplicaciones = []
        proveedor = None
        for i, fid in enumerate(factura_ids):
            monto = decimal.Decimal(montos[i] or '0')
            if monto <= 0:
                continue
            factura = get_object_or_404(FacturaProveedor, id=fid, empresa=empresa)
            proveedor = factura.proveedor
            aplicaciones.append({
                'factura': factura,
                'monto_aplicado': monto,
                'tipo_cambio': tipos_cambio[i] if i < len(tipos_cambio) else '1',
            })

        moneda = get_object_or_404(Moneda, id=request.POST.get('moneda'), empresa=empresa)
        metodo = MetodoPago.objects.filter(id=request.POST.get('metodo'), empresa=empresa).first()

        try:
            pago = services.registrar_pago(
                empresa=empresa, tipo='EGRESO', proveedor=proveedor,
                fecha=request.POST.get('fecha'), moneda=moneda, metodo=metodo,
                usuario=request.user, aplicaciones=aplicaciones,
                cuenta_banco=request.POST.get('cuenta_banco'),
                referencia=request.POST.get('referencia'),
                notas=request.POST.get('notas'),
            )
        except services.ErrorPago as e:
            messages.error(request, str(e))
            return redirect('admon_finanzas:registrar_pago')

        messages.success(request, f"Pago {pago.folio} registrado por {moneda.simbolo}{pago.monto}.")
        return redirect('admon_finanzas:historial_pagos')


class AdjuntarComplementoView(LoginRequiredMixin, View):
    """Sube el complemento de pago (REP) que el proveedor emite, normalmente
    días después del pago."""
    def post(self, request, pk):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        pago = get_object_or_404(Pago, pk=pk, empresa=empresa)
        pago.uuid_complemento = request.POST.get('uuid_complemento') or None
        pago.fecha_complemento = request.POST.get('fecha_complemento') or None
        if request.FILES.get('complemento_xml'):
            pago.complemento_xml = request.FILES['complemento_xml']
        if request.FILES.get('complemento_pdf'):
            pago.complemento_pdf = request.FILES['complemento_pdf']
        pago.save()
        messages.success(request, f"Complemento de pago adjuntado a {pago.folio}.")
        return redirect('admon_finanzas:historial_pagos')


class EstadoCuentaClientePDFView(LoginRequiredMixin, View):
    """Estado de cuenta: CxC de un cliente con saldos pendientes."""
    def get(self, request, cliente_id):
        if not request.empresa:
            return redirect('home')
        import io
        from django.template.loader import get_template
        from admon_ventas.models import Cliente
        cliente = get_object_or_404(Cliente, id=cliente_id, empresa=request.empresa)
        facturas = FacturaCliente.objects.filter(
            empresa=request.empresa, cliente=cliente).exclude(estado='CANCELADA').select_related('moneda', 'pedido')
        pendientes = [f for f in facturas if f.saldo > 0]
        total_saldo = sum((f.saldo for f in pendientes), __import__('decimal').Decimal('0'))
        html = get_template('admon_finanzas/estado_cuenta_pdf.html').render({
            'empresa': request.empresa, 'cliente': cliente,
            'facturas': facturas, 'pendientes': pendientes,
            'total_saldo': total_saldo,
            'hoy': __import__('django.utils.timezone', fromlist=['now']).now(),
        })
        from xhtml2pdf import pisa
        result = io.BytesIO()
        pdf = pisa.pisaDocument(io.BytesIO(html.encode('UTF-8')), result)
        if pdf.err:
            return HttpResponse("Error al generar el PDF", status=400)
        resp = HttpResponse(result.getvalue(), content_type='application/pdf')
        resp['Content-Disposition'] = f'inline; filename="EdoCuenta-{cliente.id}.pdf"'
        return resp


class PagoPDFView(LoginRequiredMixin, View):
    """Recibo de cobro (INGRESO) o comprobante de pago (EGRESO)."""
    def get(self, request, pk):
        if not request.empresa:
            return redirect('home')
        import io
        from django.template.loader import get_template
        pago = get_object_or_404(
            Pago.objects.select_related('proveedor', 'cliente', 'moneda', 'metodo'),
            pk=pk, empresa=request.empresa)
        html = get_template('admon_finanzas/recibo_pago.html').render({
            'pago': pago,
            'empresa': request.empresa,
            'aplicaciones': pago.aplicaciones.select_related('factura', 'factura_cliente'),
            'es_ingreso': pago.tipo == Pago.TIPO_INGRESO,
        })
        from xhtml2pdf import pisa
        result = io.BytesIO()
        pdf = pisa.pisaDocument(io.BytesIO(html.encode('UTF-8')), result)
        if pdf.err:
            return HttpResponse("Error al generar el PDF", status=400)
        resp = HttpResponse(result.getvalue(), content_type='application/pdf')
        resp['Content-Disposition'] = f'inline; filename="{pago.folio}.pdf"'
        return resp


class HistorialPagosView(LoginRequiredMixin, View):
    template_name = 'admon_finanzas/historial_pagos.html'

    def get(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        from admon_empresas import listas
        from django.urls import reverse

        qs = Pago.objects.filter(empresa=empresa).select_related(
            'proveedor', 'cliente', 'moneda', 'metodo').prefetch_related(
            'aplicaciones__factura', 'aplicaciones__factura_cliente')

        res = listas.construir(
            request, qs,
            placeholder='Folio, referencia, proveedor o cliente',
            search_header=('folio', 'referencia', 'proveedor__nombre_fiscal',
                           'proveedor__nombre_comercial', 'cliente__nombre_fiscal',
                           'cliente__nombre_comercial'),
            date_field='fecha',
            exactos={'tipo': 'tipo'},
            filtros_ui=[
                {'name': 'tipo', 'label': 'Tipo', 'tipo': 'select',
                 'opciones': Pago.TIPO_CHOICES},
                {'name': 'desde', 'label': 'Desde', 'tipo': 'date'},
                {'name': 'hasta', 'label': 'Hasta', 'tipo': 'date'},
            ],
            sum_fields=('monto',),
            clear_url=reverse('admon_finanzas:historial_pagos'),
            export_nombre='pagos',
            export_order=('-fecha', '-id'),
            export_columnas=[
                ('Folio', 'folio'), ('Tipo', 'get_tipo_display'),
                ('Tercero', lambda o: str(o.cliente or o.proveedor or '')),
                ('Fecha', lambda o: o.fecha.strftime('%d/%m/%Y') if o.fecha else ''),
                ('Referencia', 'referencia'), ('Monto', 'monto'),
                ('Moneda', lambda o: o.moneda.codigo if o.moneda else '')],
        )
        if res['export']:
            return res['export']
        context = {
            'pagos': res['page_obj'], 'page_obj': res['page_obj'],
            'totales': res['totales'], 'lista': res['lista'],
            'sucursal_activa': sucursal,
            'seccion': 'finanzas',
        }
        return render(request, self.template_name, context)


# --------------------------------------------------------------------------
# CUENTAS POR COBRAR (clientes)
# --------------------------------------------------------------------------
class CuentasPorCobrarView(LoginRequiredMixin, View):
    template_name = 'admon_finanzas/cuentas_por_cobrar.html'

    def get(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        from admon_empresas import listas
        from django.urls import reverse
        from admon_ventas.models import Cliente

        qs = FacturaCliente.objects.filter(empresa=empresa).select_related(
            'cliente', 'moneda', 'pedido').prefetch_related('aplicaciones')

        res = listas.construir(
            request, qs,
            placeholder='Folio, UUID, cliente o notas',
            search_header=('folio', 'uuid_cfdi', 'cliente__nombre_fiscal',
                           'cliente__nombre_comercial', 'notas'),
            date_field='fecha_emision',
            exactos={'estado': 'estado', 'cliente': 'cliente_id'},
            filtros_ui=[
                {'name': 'estado', 'label': 'Estado', 'tipo': 'select',
                 'opciones': FacturaCliente.ESTADO_CHOICES},
                {'name': 'cliente', 'label': 'Cliente', 'tipo': 'select',
                 'opciones': [(c.id, str(c)) for c in
                              Cliente.objects.filter(empresa=empresa).order_by('nombre_fiscal')]},
                {'name': 'desde', 'label': 'Desde', 'tipo': 'date'},
                {'name': 'hasta', 'label': 'Hasta', 'tipo': 'date'},
            ],
            sum_fields=('subtotal', 'impuestos', 'total'),
            clear_url=reverse('admon_finanzas:cuentas_por_cobrar'),
            export_nombre='cuentas_por_cobrar',
            export_order=('-fecha_emision', '-id'),
            export_columnas=[
                ('Folio', 'folio'), ('Cliente', lambda o: str(o.cliente)),
                ('UUID', 'uuid_cfdi'), ('Estado', 'get_estado_display'),
                ('Emisión', lambda o: o.fecha_emision.strftime('%d/%m/%Y') if o.fecha_emision else ''),
                ('Total', 'total'), ('Saldo', lambda o: o.saldo),
                ('Moneda', lambda o: o.moneda.codigo if o.moneda else '')],
        )
        if res['export']:
            return res['export']

        por_cobrar = {}
        for f in res['qs']:
            if f.estado in ('PENDIENTE', 'PARCIAL'):
                cod = f.moneda.codigo
                por_cobrar[cod] = por_cobrar.get(cod, decimal.Decimal('0')) + f.saldo

        context = {
            'facturas': res['page_obj'], 'page_obj': res['page_obj'],
            'totales': res['totales'], 'lista': res['lista'],
            'resumen_por_cobrar': por_cobrar,
            'sucursal_activa': sucursal,
            'seccion': 'finanzas',
        }
        return render(request, self.template_name, context)


class FacturaClienteDetalleView(LoginRequiredMixin, View):
    template_name = 'admon_finanzas/factura_cliente_detalle.html'

    def get(self, request, pk):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        factura = get_object_or_404(
            FacturaCliente.objects.select_related('cliente', 'moneda', 'pedido'),
            pk=pk, empresa=empresa)
        context = {
            'factura': factura,
            'aplicaciones': factura.aplicaciones.select_related('pago', 'pago__metodo'),
            'sucursal_activa': sucursal,
            'seccion': 'finanzas',
        }
        return render(request, self.template_name, context)

    def post(self, request, pk):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        factura = get_object_or_404(FacturaCliente, pk=pk, empresa=empresa)
        accion = request.POST.get('accion')
        if accion == 'subir_cfdi':
            xml = request.FILES.get('archivo_xml')
            pdf = request.FILES.get('archivo_pdf')
            uuid = (request.POST.get('uuid_cfdi') or '').strip()
            if xml:
                factura.archivo_xml = xml
            if pdf:
                factura.archivo_pdf = pdf
            if uuid:
                factura.uuid_cfdi = uuid
            factura.save()
            messages.success(request, "CFDI adjuntado a la cuenta por cobrar.")
        elif accion == 'cancelar' and factura.total_pagado == 0:
            factura.estado = 'CANCELADA'
            factura.save(update_fields=['estado'])
            messages.info(request, f"CxC {factura.folio} cancelada.")
        else:
            messages.error(request, "No se puede cancelar una factura con cobros aplicados.")
        return redirect('admon_finanzas:factura_cliente_detalle', pk=pk)


class RegistrarCobroView(LoginRequiredMixin, View):
    template_name = 'admon_finanzas/cobro_form.html'

    def get(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        context = {
            'facturas': services.facturas_por_cobrar(empresa),
            'metodos': MetodoPago.objects.filter(empresa=empresa, activo=True),
            'monedas': Moneda.objects.filter(empresa=empresa, activa=True),
            'moneda_base': empresa.moneda_principal,
            'sucursal_activa': sucursal,
            'seccion': 'finanzas',
        }
        return render(request, self.template_name, context)

    def post(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx

        factura_ids = request.POST.getlist('factura_id[]')
        montos = request.POST.getlist('monto_aplicado[]')
        tipos_cambio = request.POST.getlist('tipo_cambio[]')

        aplicaciones = []
        cliente = None
        for i, fid in enumerate(factura_ids):
            monto = decimal.Decimal(montos[i] or '0')
            if monto <= 0:
                continue
            factura = get_object_or_404(FacturaCliente, id=fid, empresa=empresa)
            cliente = factura.cliente
            aplicaciones.append({
                'factura': factura,
                'monto_aplicado': monto,
                'tipo_cambio': tipos_cambio[i] if i < len(tipos_cambio) else '1',
            })

        moneda = get_object_or_404(Moneda, id=request.POST.get('moneda'), empresa=empresa)
        metodo = MetodoPago.objects.filter(id=request.POST.get('metodo'), empresa=empresa).first()

        try:
            cobro = services.registrar_cobro(
                empresa=empresa, cliente=cliente,
                fecha=request.POST.get('fecha'), moneda=moneda, metodo=metodo,
                usuario=request.user, aplicaciones=aplicaciones,
                cuenta_banco=request.POST.get('cuenta_banco'),
                referencia=request.POST.get('referencia'),
                notas=request.POST.get('notas'),
            )
        except services.ErrorPago as e:
            messages.error(request, str(e))
            return redirect('admon_finanzas:registrar_cobro')

        messages.success(request, f"Cobro {cobro.folio} registrado por {moneda.simbolo}{cobro.monto}.")
        return redirect('admon_finanzas:cuentas_por_cobrar')


# --------------------------------------------------------------------------
# ESTADO DE RESULTADOS (Fase 1: utilidad bruta por periodo)
# --------------------------------------------------------------------------
class EstadoResultadosView(LoginRequiredMixin, View):
    """Estado de resultados simplificado: Ventas netas − Costo de ventas =
    Utilidad bruta, por rango de fechas, con desglose mensual. Base: lo
    entregado (pedidos ENTREGADO/parcial), todo sin IVA."""
    template_name = 'admon_finanzas/estado_resultados.html'

    def get(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        from datetime import date
        from admon_ventas.models import DetallePedido
        D = decimal.Decimal

        hoy = date.today()
        desde = (request.GET.get('desde') or date(hoy.year, 1, 1).isoformat()).strip()
        hasta = (request.GET.get('hasta') or hoy.isoformat()).strip()

        dets = DetallePedido.objects.filter(
            pedido__empresa=empresa,
            pedido__estado__in=['ENTREGADO', 'ENTREGADO_PARCIAL'],
            pedido__fecha_emision__gte=desde,
            pedido__fecha_emision__lte=hasta,
        ).select_related('producto', 'pedido')

        ventas = D('0'); costo = D('0')
        meses = {}  # 'YYYY-MM' -> {ventas, costo}
        for det in dets:
            qty = det.cantidad_entregada or D('0')
            if qty <= 0:
                continue
            v = qty * det.precio_unitario
            c = qty * (det.producto.costo_unitario or D('0'))
            ventas += v; costo += c
            k = det.pedido.fecha_emision.strftime('%Y-%m')
            m = meses.setdefault(k, {'ventas': D('0'), 'costo': D('0')})
            m['ventas'] += v; m['costo'] += c

        util = ventas - costo
        margen = (util / ventas * 100) if ventas else D('0')

        filas_mes = []
        for k in sorted(meses):
            mv = meses[k]['ventas']; mc = meses[k]['costo']
            filas_mes.append({
                'mes': k, 'ventas': mv, 'costo': mc, 'utilidad': mv - mc,
                'margen': ((mv - mc) / mv * 100) if mv else D('0')})

        # Exportar a Excel (CSV)
        if request.GET.get('export') == 'csv':
            import csv as _csv
            resp = HttpResponse(content_type='text/csv; charset=utf-8-sig')
            resp['Content-Disposition'] = f'attachment; filename="estado_resultados_{desde}_a_{hasta}.csv"'
            resp.write('﻿')
            w = _csv.writer(resp)
            w.writerow(['Mes', 'Ventas netas', 'Costo de ventas', 'Utilidad bruta', 'Margen %'])
            for f in filas_mes:
                w.writerow([f['mes'], f['ventas'].quantize(D('0.01')), f['costo'].quantize(D('0.01')),
                            f['utilidad'].quantize(D('0.01')), f"{f['margen']:.1f}"])
            w.writerow(['TOTAL', ventas.quantize(D('0.01')), costo.quantize(D('0.01')),
                        util.quantize(D('0.01')), f"{margen:.1f}"])
            return resp

        context = {
            'desde': desde, 'hasta': hasta,
            'ventas': ventas, 'costo': costo, 'utilidad': util, 'margen': margen,
            'filas_mes': filas_mes,
            'sucursal_activa': sucursal, 'seccion': 'finanzas',
        }
        return render(request, self.template_name, context)
