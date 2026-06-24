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
        from django.db.models import Sum, Q
        agg = res['qs'].aggregate(
            egreso=Sum('monto', filter=Q(tipo='EGRESO')),
            ingreso=Sum('monto', filter=Q(tipo='INGRESO')))
        Z = decimal.Decimal('0')
        totales_tipo = {
            'egreso': agg['egreso'] or Z,
            'ingreso': agg['ingreso'] or Z,
            'neto': (agg['ingreso'] or Z) - (agg['egreso'] or Z),
        }
        context = {
            'pagos': res['page_obj'], 'page_obj': res['page_obj'],
            'totales': res['totales'], 'lista': res['lista'],
            'totales_tipo': totales_tipo,
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
            'cliente', 'moneda', 'pedido').prefetch_related('aplicaciones', 'cfdis')

        # Filtro de facturación (una CxC está facturada si tiene UUID o XML)
        from django.db.models import Q
        facturada_q = Q(uuid_cfdi__gt='') | Q(archivo_xml__gt='')
        f_fact = (request.GET.get('facturacion') or '').strip()
        if f_fact == 'si':
            qs = qs.filter(facturada_q)
        elif f_fact == 'no':
            qs = qs.exclude(facturada_q)

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
                {'name': 'facturacion', 'label': 'Facturación', 'tipo': 'select',
                 'opciones': [('si', 'Facturado'), ('no', 'Sin factura')],
                 'todos': 'Todas'},
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
        Z = decimal.Decimal('0')
        kpi = {'pendiente_facturar': Z, 'por_cobrar_sin_factura': Z,
               'facturado_por_cobrar': Z, 'total_por_cobrar': Z}
        for f in res['qs']:
            abierta = f.estado in ('PENDIENTE', 'PARCIAL')
            if abierta:
                cod = f.moneda.codigo
                por_cobrar[cod] = por_cobrar.get(cod, Z) + f.saldo
                kpi['total_por_cobrar'] += f.saldo
            if f.estado == 'CANCELADA':
                continue
            if not f.esta_facturada:
                # Lo que falta por timbrar (total de lo no facturado, vigente)
                kpi['pendiente_facturar'] += f.total
                if abierta:
                    kpi['por_cobrar_sin_factura'] += f.saldo
            elif abierta:
                kpi['facturado_por_cobrar'] += f.saldo

        context = {
            'facturas': res['page_obj'], 'page_obj': res['page_obj'],
            'totales': res['totales'], 'lista': res['lista'],
            'resumen_por_cobrar': por_cobrar,
            'kpi': kpi,
            'sucursal_activa': sucursal,
            'seccion': 'finanzas',
        }
        return render(request, self.template_name, context)


class ExcelFacturacionView(LoginRequiredMixin, View):
    """Genera un Excel para el contador con el detalle (partida por partida) de
    las CxC seleccionadas que hay que facturar."""

    def get(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, _sucursal = ctx
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        from django.utils import timezone as _tz

        ids = request.GET.getlist('ids')
        cxcs = (FacturaCliente.objects.filter(empresa=empresa, id__in=ids)
                .exclude(estado='CANCELADA')
                .select_related('cliente', 'moneda', 'pedido')
                .prefetch_related('pedido__detalles__producto'))
        if not cxcs:
            messages.warning(request, "Selecciona al menos una cuenta por cobrar para facturar.")
            return redirect('admon_finanzas:cuentas_por_cobrar')

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Por facturar"
        cols = ['Cliente', 'RFC', 'CxC', 'Pedido', 'Fecha', 'SKU', 'Descripción',
                'Cantidad', 'P. Unitario', 'Importe', 'IVA %', 'IVA', 'Total']
        ws.append(cols)
        head_fill = PatternFill('solid', fgColor='0F172A')
        for c in ws[1]:
            c.font = Font(bold=True, color='FFFFFF', size=10)
            c.fill = head_fill
            c.alignment = Alignment(horizontal='center')

        D = decimal.Decimal
        tot_imp = tot_iva = tot_tot = D('0')
        for f in cxcs:
            cliente = f.cliente.nombre_fiscal
            rfc = (f.cliente.rfc or '').upper()
            fecha = f.fecha_emision.strftime('%d/%m/%Y') if f.fecha_emision else ''
            dets = f.pedido.detalles.all() if f.pedido_id else []
            for d in dets:
                importe = (d.cantidad * d.precio_unitario).quantize(D('0.01'))
                tasa = d.iva_porcentaje or D('0')
                iva = (importe * tasa / 100).quantize(D('0.01'))
                if d.es_retencion:
                    iva = -iva
                total = importe + iva
                ws.append([
                    cliente, rfc, f.folio, f.pedido.folio if f.pedido_id else '', fecha,
                    d.producto.sku, d.producto.nombre,
                    float(d.cantidad), float(d.precio_unitario), float(importe),
                    float(tasa), float(iva), float(total)])
                tot_imp += importe; tot_iva += iva; tot_tot += total

        # Fila de totales
        ws.append([])
        fila_tot = ['', '', '', '', '', '', 'TOTALES', '', '', float(tot_imp), '',
                    float(tot_iva), float(tot_tot)]
        ws.append(fila_tot)
        for c in ws[ws.max_row]:
            c.font = Font(bold=True)

        # Anchos y formato de moneda
        anchos = [30, 14, 12, 14, 11, 16, 50, 10, 13, 14, 7, 13, 14]
        for i, w in enumerate(anchos, start=1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
        for row in ws.iter_rows(min_row=2):
            for col in (9, 10, 12, 13):
                row[col-1].number_format = '#,##0.00'

        resp = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        resp['Content-Disposition'] = (
            f'attachment; filename="por_facturar_{_tz.now():%Y%m%d_%H%M}.xlsx"')
        wb.save(resp)
        return resp


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

        util_bruta = ventas - costo
        margen = (util_bruta / ventas * 100) if ventas else D('0')

        # ---- Gastos de operación del periodo, por clasificación y categoría ----
        from .models import Gasto, CategoriaGasto
        gastos = Gasto.objects.filter(
            empresa=empresa, fecha__gte=desde, fecha__lte=hasta
        ).select_related('categoria')
        clasif_labels = dict(CategoriaGasto.CLASIF_CHOICES)
        grupos = {}  # clasif -> {'total': D, 'cats': {nombre: D}}
        total_gastos = D('0')
        for g in gastos:
            clasif = g.categoria.clasificacion
            grp = grupos.setdefault(clasif, {'total': D('0'), 'cats': {}})
            grp['total'] += g.subtotal
            grp['cats'][g.categoria.nombre] = grp['cats'].get(g.categoria.nombre, D('0')) + g.subtotal
            total_gastos += g.subtotal

        gastos_grupos = []
        for clasif, _lbl in CategoriaGasto.CLASIF_CHOICES:
            if clasif in grupos:
                grp = grupos[clasif]
                gastos_grupos.append({
                    'clasificacion': clasif_labels[clasif], 'total': grp['total'],
                    'cats': sorted(grp['cats'].items())})

        util_operacion = util_bruta - total_gastos
        margen_op = (util_operacion / ventas * 100) if ventas else D('0')

        # ---- Partidas no operativas e impuestos (Fase 3) ----
        from .models import PartidaResultado
        partidas = PartidaResultado.objects.filter(
            empresa=empresa, fecha__gte=desde, fecha__lte=hasta)
        otros_ing = D('0'); otros_egr = D('0'); impuestos = D('0')
        for p in partidas:
            if p.naturaleza == 'OTRO_INGRESO':
                otros_ing += p.monto
            elif p.naturaleza == 'OTRO_EGRESO':
                otros_egr += p.monto
            else:
                impuestos += p.monto
        util_antes_imp = util_operacion + otros_ing - otros_egr
        util_neta = util_antes_imp - impuestos
        margen_neto = (util_neta / ventas * 100) if ventas else D('0')

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
            w.writerow(['Concepto', 'Importe'])
            w.writerow(['Ventas netas', ventas.quantize(D('0.01'))])
            w.writerow(['Costo de ventas', (-costo).quantize(D('0.01'))])
            w.writerow(['Utilidad bruta', util_bruta.quantize(D('0.01'))])
            for grp in gastos_grupos:
                w.writerow([f"({grp['clasificacion']})", (-grp['total']).quantize(D('0.01'))])
                for nombre, monto in grp['cats']:
                    w.writerow([f"   {nombre}", (-monto).quantize(D('0.01'))])
            w.writerow(['Total gastos de operación', (-total_gastos).quantize(D('0.01'))])
            w.writerow(['Utilidad de operación', util_operacion.quantize(D('0.01'))])
            if otros_ing:
                w.writerow(['(+) Otros ingresos', otros_ing.quantize(D('0.01'))])
            if otros_egr:
                w.writerow(['(−) Otros gastos', (-otros_egr).quantize(D('0.01'))])
            w.writerow(['Utilidad antes de impuestos', util_antes_imp.quantize(D('0.01'))])
            w.writerow(['(−) Impuestos', (-impuestos).quantize(D('0.01'))])
            w.writerow(['Utilidad neta', util_neta.quantize(D('0.01'))])
            w.writerow([])
            w.writerow(['Mes', 'Ventas netas', 'Costo de ventas', 'Utilidad bruta', 'Margen %'])
            for f in filas_mes:
                w.writerow([f['mes'], f['ventas'].quantize(D('0.01')), f['costo'].quantize(D('0.01')),
                            f['utilidad'].quantize(D('0.01')), f"{f['margen']:.1f}"])
            return resp

        context = {
            'desde': desde, 'hasta': hasta,
            'ventas': ventas, 'costo': costo, 'utilidad': util_bruta, 'margen': margen,
            'gastos_grupos': gastos_grupos, 'total_gastos': total_gastos,
            'util_operacion': util_operacion, 'margen_op': margen_op,
            'otros_ing': otros_ing, 'otros_egr': otros_egr, 'impuestos': impuestos,
            'util_antes_imp': util_antes_imp, 'util_neta': util_neta, 'margen_neto': margen_neto,
            'filas_mes': filas_mes,
            'sucursal_activa': sucursal, 'seccion': 'finanzas',
        }
        return render(request, self.template_name, context)


# --------------------------------------------------------------------------
# GASTOS DE OPERACIÓN (Fase 2)
# --------------------------------------------------------------------------
CATEGORIAS_SEED = [
    ('Comisiones de venta', 'VENTA'), ('Envíos y paquetería', 'VENTA'),
    ('Publicidad y marketing', 'VENTA'),
    ('Renta', 'ADMIN'), ('Servicios (luz, agua, internet)', 'ADMIN'),
    ('Sueldos y honorarios', 'ADMIN'), ('Papelería y oficina', 'ADMIN'),
    ('Software y suscripciones', 'ADMIN'),
    ('Comisiones bancarias', 'FINANCIERO'), ('Intereses', 'FINANCIERO'),
    ('Otros gastos', 'OTRO'),
]


def _seed_categorias(empresa):
    from .models import CategoriaGasto
    if not CategoriaGasto.objects.filter(empresa=empresa).exists():
        CategoriaGasto.objects.bulk_create([
            CategoriaGasto(empresa=empresa, nombre=n, clasificacion=c)
            for n, c in CATEGORIAS_SEED])


class GastosView(LoginRequiredMixin, View):
    template_name = 'admon_finanzas/gastos.html'

    def get(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        from .models import Gasto, CategoriaGasto
        from admon_empresas import listas
        from django.urls import reverse
        _seed_categorias(empresa)

        qs = Gasto.objects.filter(empresa=empresa).select_related('categoria', 'metodo')
        cats = CategoriaGasto.objects.filter(empresa=empresa, activo=True)
        res = listas.construir(
            request, qs,
            placeholder='Descripción, proveedor o referencia',
            search_header=('descripcion', 'proveedor_nombre', 'referencia'),
            date_field='fecha',
            exactos={'categoria': 'categoria_id', 'clasificacion': 'categoria__clasificacion'},
            filtros_ui=[
                {'name': 'categoria', 'label': 'Categoría', 'tipo': 'select',
                 'opciones': [(c.id, c.nombre) for c in cats]},
                {'name': 'clasificacion', 'label': 'Clasificación', 'tipo': 'select',
                 'opciones': CategoriaGasto.CLASIF_CHOICES},
                {'name': 'desde', 'label': 'Desde', 'tipo': 'date'},
                {'name': 'hasta', 'label': 'Hasta', 'tipo': 'date'},
            ],
            sum_fields=('subtotal', 'iva', 'total'),
            clear_url=reverse('admon_finanzas:gastos'),
            export_nombre='gastos', export_order=('-fecha', '-id'),
            export_columnas=[
                ('Fecha', lambda o: o.fecha.strftime('%d/%m/%Y') if o.fecha else ''),
                ('Categoría', lambda o: o.categoria.nombre),
                ('Clasificación', lambda o: o.categoria.get_clasificacion_display()),
                ('Descripción', 'descripcion'), ('Proveedor', 'proveedor_nombre'),
                ('Subtotal', 'subtotal'), ('IVA', 'iva'), ('Total', 'total'),
                ('Referencia', 'referencia')],
        )
        if res['export']:
            return res['export']
        context = {
            'gastos': res['page_obj'], 'page_obj': res['page_obj'],
            'totales': res['totales'], 'lista': res['lista'],
            'categorias': cats,
            'sucursal_activa': sucursal, 'seccion': 'finanzas',
        }
        return render(request, self.template_name, context)

    def post(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        from .models import Gasto, CategoriaGasto
        accion = request.POST.get('accion')

        if accion == 'eliminar':
            g = get_object_or_404(Gasto, id=request.POST.get('gasto_id'), empresa=empresa)
            g.delete()
            messages.success(request, "Gasto eliminado.")
            return redirect('admon_finanzas:gastos')

        if accion == 'nueva_categoria':
            nombre = (request.POST.get('cat_nombre') or '').strip()
            clasif = request.POST.get('cat_clasificacion') or 'ADMIN'
            if nombre:
                CategoriaGasto.objects.get_or_create(
                    empresa=empresa, nombre=nombre, defaults={'clasificacion': clasif})
                messages.success(request, f"Categoría '{nombre}' creada.")
            return redirect('admon_finanzas:gastos')

        # Alta de gasto
        try:
            categoria = get_object_or_404(
                CategoriaGasto, id=request.POST.get('categoria'), empresa=empresa)
            subtotal = decimal.Decimal(request.POST.get('subtotal') or '0')
            iva = decimal.Decimal(request.POST.get('iva') or '0')
            if iva == 0 and request.POST.get('aplica_iva') == 'on':
                iva = (subtotal * decimal.Decimal('0.16')).quantize(decimal.Decimal('0.01'))
            g = Gasto.objects.create(
                empresa=empresa, sucursal=sucursal, categoria=categoria,
                fecha=request.POST.get('fecha'),
                descripcion=(request.POST.get('descripcion') or '').strip(),
                proveedor_nombre=(request.POST.get('proveedor_nombre') or '').strip(),
                subtotal=subtotal, iva=iva, total=subtotal + iva,
                referencia=(request.POST.get('referencia') or '').strip(),
                uuid_cfdi=(request.POST.get('uuid_cfdi') or '').strip() or None,
                comprobante=request.FILES.get('comprobante'),
                creado_por=request.user)
            messages.success(request, f"Gasto registrado: ${g.total}.")
        except Exception as e:
            messages.error(request, f"No se pudo registrar el gasto: {e}")
        return redirect('admon_finanzas:gastos')


# --------------------------------------------------------------------------
# OTROS RESULTADOS E IMPUESTOS (Fase 3)
# --------------------------------------------------------------------------
class OtrosResultadosView(LoginRequiredMixin, View):
    template_name = 'admon_finanzas/otros_resultados.html'

    def get(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        from .models import PartidaResultado
        from admon_empresas import listas
        from django.urls import reverse

        qs = PartidaResultado.objects.filter(empresa=empresa)
        res = listas.construir(
            request, qs,
            placeholder='Concepto o referencia',
            search_header=('concepto', 'referencia'),
            date_field='fecha',
            exactos={'naturaleza': 'naturaleza'},
            filtros_ui=[
                {'name': 'naturaleza', 'label': 'Naturaleza', 'tipo': 'select',
                 'opciones': PartidaResultado.NATURALEZA_CHOICES},
                {'name': 'desde', 'label': 'Desde', 'tipo': 'date'},
                {'name': 'hasta', 'label': 'Hasta', 'tipo': 'date'},
            ],
            sum_fields=('monto',),
            clear_url=reverse('admon_finanzas:otros_resultados'),
            export_nombre='otros_resultados', export_order=('-fecha', '-id'),
            export_columnas=[
                ('Fecha', lambda o: o.fecha.strftime('%d/%m/%Y') if o.fecha else ''),
                ('Naturaleza', 'get_naturaleza_display'), ('Concepto', 'concepto'),
                ('Monto', 'monto'), ('Referencia', 'referencia')],
        )
        if res['export']:
            return res['export']
        context = {
            'partidas': res['page_obj'], 'page_obj': res['page_obj'],
            'totales': res['totales'], 'lista': res['lista'],
            'naturalezas': PartidaResultado.NATURALEZA_CHOICES,
            'sucursal_activa': sucursal, 'seccion': 'finanzas',
        }
        return render(request, self.template_name, context)

    def post(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        from .models import PartidaResultado
        if request.POST.get('accion') == 'eliminar':
            p = get_object_or_404(PartidaResultado, id=request.POST.get('partida_id'), empresa=empresa)
            p.delete()
            messages.success(request, "Partida eliminada.")
            return redirect('admon_finanzas:otros_resultados')
        try:
            PartidaResultado.objects.create(
                empresa=empresa, naturaleza=request.POST.get('naturaleza'),
                fecha=request.POST.get('fecha'),
                concepto=(request.POST.get('concepto') or '').strip(),
                monto=decimal.Decimal(request.POST.get('monto') or '0'),
                referencia=(request.POST.get('referencia') or '').strip(),
                creado_por=request.user)
            messages.success(request, "Partida registrada.")
        except Exception as e:
            messages.error(request, f"No se pudo registrar: {e}")
        return redirect('admon_finanzas:otros_resultados')


# --------------------------------------------------------------------------
# CONCILIACIÓN SAT (CFDI emitidos/recibidos vs sistema)
# --------------------------------------------------------------------------
class ConciliacionSATView(LoginRequiredMixin, View):
    template_name = 'admon_finanzas/conciliacion_sat.html'

    def get(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        from . import conciliacion as conc

        filtro = (request.GET.get('estado') or '').strip()  # '', CONCILIADO, SIN_UUID, FALTANTE
        direccion = (request.GET.get('direccion') or '').strip()
        filas = conc.conciliar(empresa)

        resumen = {'CONCILIADO': 0, 'SIN_UUID': 0, 'FALTANTE': 0,
                   'EMITIDO': 0, 'RECIBIDO': 0}
        for f in filas:
            resumen[f['estado']] += 1
            resumen[f['comp'].direccion] += 1

        if filtro:
            filas = [f for f in filas if f['estado'] == filtro]
        if direccion:
            filas = [f for f in filas if f['comp'].direccion == direccion]

        context = {
            'filas': filas, 'resumen': resumen,
            'filtro': filtro, 'direccion_f': direccion,
            'rfc_empresa': empresa.rfc,
            'sucursal_activa': sucursal, 'seccion': 'finanzas',
        }
        return render(request, self.template_name, context)

    def post(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        from . import conciliacion as conc
        from .models import ComprobanteSAT, Gasto, CategoriaGasto, FacturaCliente, FacturaProveedor
        accion = request.POST.get('accion')

        if accion == 'cargar':
            archivos = request.FILES.getlist('archivos')
            if not archivos:
                messages.error(request, "Selecciona uno o más XML (o un ZIP) del SAT.")
                return redirect('admon_finanzas:conciliacion_sat')
            try:
                r = conc.cargar_comprobantes(archivos, empresa)
            except Exception as e:
                messages.error(request, f"No se pudieron procesar los archivos: {e}")
                return redirect('admon_finanzas:conciliacion_sat')
            messages.success(
                request, f"CFDI leídos: {r['leidos']} ({r['emitidos']} emitidos, "
                f"{r['recibidos']} recibidos, {r['nuevos']} nuevos). "
                f"Ajenos a tu RFC: {r['ajenos']}, no-CFDI: {r['no_cfdi']}.")
            return redirect('admon_finanzas:conciliacion_sat')

        if accion == 'limpiar':
            ComprobanteSAT.objects.filter(empresa=empresa).delete()
            messages.info(request, "Comprobantes SAT borrados (puedes volver a cargar).")
            return redirect('admon_finanzas:conciliacion_sat')

        if accion == 'eliminar_comp':
            ComprobanteSAT.objects.filter(
                id=request.POST.get('comprobante_id'), empresa=empresa).delete()
            messages.info(request, "Comprobante quitado de la conciliación.")
            return redirect('admon_finanzas:conciliacion_sat')

        comp = get_object_or_404(ComprobanteSAT, id=request.POST.get('comprobante_id'), empresa=empresa)

        if accion == 'marcar_uuid':
            # Buscar el documento candidato y ponerle el UUID
            doc = None
            if comp.direccion == 'EMITIDO':
                doc = conc.FacturaClienteCand(empresa, comp)
            else:
                cand = conc.FacturaProvCand(empresa, comp) or conc.GastoCand(empresa, comp)
                doc = cand[0] if cand else None
            if doc:
                doc.uuid_cfdi = comp.uuid
                doc.save(update_fields=['uuid_cfdi'])
                messages.success(request, f"UUID asignado a {doc.folio if hasattr(doc,'folio') else doc}.")
            else:
                messages.error(request, "Ya no se encontró un documento que coincida por monto y fecha.")
            return redirect('admon_finanzas:conciliacion_sat')

        if accion == 'alta_gasto':
            if comp.direccion != 'RECIBIDO':
                messages.error(request, "Solo los CFDI recibidos se dan de alta como gasto.")
                return redirect('admon_finanzas:conciliacion_sat')
            cat, _ = CategoriaGasto.objects.get_or_create(
                empresa=empresa, nombre='Gastos por CFDI', defaults={'clasificacion': 'ADMIN'})
            Gasto.objects.create(
                empresa=empresa, sucursal=sucursal, categoria=cat, fecha=comp.fecha,
                descripcion=(comp.serie_folio and f"CFDI {comp.serie_folio}") or "Gasto CFDI",
                proveedor_nombre=comp.nombre_emisor[:160],
                subtotal=comp.subtotal, iva=comp.iva, total=comp.total,
                uuid_cfdi=comp.uuid, referencia=comp.serie_folio, creado_por=request.user)
            messages.success(request, f"Gasto creado desde el CFDI por ${comp.total} (revisa su categoría en Gastos).")
            return redirect('admon_finanzas:conciliacion_sat')

        return redirect('admon_finanzas:conciliacion_sat')
