import decimal
import io
from datetime import datetime

from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.template.loader import get_template
from django.utils import timezone

from admon_empresas.models import Moneda, Sucursal, Impuesto
from admon_inventarios.models import Producto
from .models import (
    Proveedor, OrdenCompra, DetalleOrdenCompra, AutorizadorCompra,
)
from .forms import ProveedorForm, AutorizadorCompraForm
from . import services
from . import import_proveedores


# --------------------------------------------------------------------------
# Helpers de contexto (reutilizan la lógica de inventarios)
# --------------------------------------------------------------------------
def _contexto(request):
    if not request.empresa:
        messages.warning(request, "No hay una empresa activa.")
        return None
    if not request.sucursal_activa:
        messages.warning(request, "No hay una sucursal activa. Selecciona una sede arriba.")
        return None
    return request.empresa, request.sucursal_activa


def _es_admin(request):
    if request.user.is_superuser:
        return True
    perfil = getattr(request.user, 'perfil', None)
    if perfil and perfil.tipo_usuario == 'OWNER':
        return True
    return bool(request.sucursal_activa and request.sucursal_activa.es_matriz)


def proveedores_visibles(empresa, sucursal):
    return Proveedor.objects.filter(empresa=empresa, activo=True).filter(
        Q(sucursales_acceso=sucursal) | Q(sucursales_acceso__isnull=True)
    ).distinct()


def _aplicar_partidas(orden, empresa, request):
    """Reescribe las partidas de la orden y recalcula totales usando el
    catálogo de impuestos. Traslados suman, retenciones restan."""
    productos_ids = request.POST.getlist('producto[]')
    cantidades = request.POST.getlist('cantidad[]')
    precios = request.POST.getlist('precio[]')
    impuestos_ids = request.POST.getlist('impuesto[]')

    default_imp = Impuesto.objects.filter(empresa=empresa, es_default=True).first()

    orden.detalles.all().delete()
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

        sub = cant * prec
        monto = sub * (tasa / 100)
        DetalleOrdenCompra.objects.create(
            orden=orden, producto_id=pid, cantidad_pedida=cant,
            precio_unitario=prec, impuesto=imp, iva_porcentaje=tasa, es_retencion=es_ret)
        subtotal += sub
        imp_total += (-monto if es_ret else monto)

    orden.subtotal = subtotal
    orden.impuestos = imp_total
    orden.total = subtotal + imp_total
    orden.save()


# --------------------------------------------------------------------------
# PROVEEDORES
# --------------------------------------------------------------------------
class ProveedoresView(LoginRequiredMixin, View):
    template_name = 'admon_compras/proveedores.html'

    def get(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        context = {
            'proveedores': Proveedor.objects.filter(empresa=empresa).prefetch_related('sucursales_acceso'),
            'form': ProveedorForm(empresa=empresa),
            'sucursal_activa': sucursal,
            'seccion': 'compras',
        }
        return render(request, self.template_name, context)

    def post(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx

        action = request.POST.get('action')
        if action == 'delete':
            prov = get_object_or_404(Proveedor, id=request.POST.get('item_id'), empresa=empresa)
            try:
                prov.delete()
                messages.success(request, "Proveedor eliminado.")
            except Exception:
                prov.activo = False
                prov.save()
                messages.info(request, "El proveedor tiene órdenes asociadas: se desactivó.")
            return redirect('admon_compras:proveedores')

        item_id = request.POST.get('item_id')
        instance = Proveedor.objects.filter(id=item_id, empresa=empresa).first() if item_id else None
        form = ProveedorForm(request.POST, instance=instance, empresa=empresa)
        if form.is_valid():
            prov = form.save(commit=False)
            prov.empresa = empresa
            prov.save()
            form.save_m2m()
            messages.success(request, "Proveedor guardado correctamente.")
        else:
            messages.error(request, f"Error en el formulario: {form.errors.as_text()}")
        return redirect('admon_compras:proveedores')


class DescargarPlantillaProveedoresView(LoginRequiredMixin, View):
    """Descarga una plantilla .xlsx (con fila de ejemplo) para carga masiva.
    Solo superuser."""
    def get(self, request):
        if not request.user.is_superuser:
            messages.error(request, "Solo el administrador puede descargar la plantilla.")
            return redirect('admon_compras:proveedores')
        contenido = import_proveedores.generar_plantilla(con_ejemplo=True)
        resp = HttpResponse(
            contenido,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        resp['Content-Disposition'] = 'attachment; filename="plantilla_proveedores.xlsx"'
        return resp


class ImportarAmazonView(LoginRequiredMixin, View):
    """Importa el CSV de pedidos de Amazon Business: crea productos y registra
    cada orden como recepción (entra stock al costo)."""
    def post(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        if not request.user.is_superuser:
            messages.error(request, "Solo el administrador puede importar compras.")
            return redirect('admon_compras:historial_ordenes')
        archivo = request.FILES.get('archivo')
        if not archivo or not archivo.name.lower().endswith('.csv'):
            messages.error(request, "Selecciona el archivo .csv exportado de Amazon.")
            return redirect('admon_compras:historial_ordenes')
        from . import import_amazon
        try:
            res = import_amazon.importar(archivo, empresa, sucursal, request.user)
        except Exception as e:
            messages.error(request, f"No se pudo procesar el archivo: {e}")
            return redirect('admon_compras:historial_ordenes')
        messages.success(
            request,
            f"Amazon importado: {res['ordenes']} órdenes de compra (con recepción + CxP pagada), "
            f"{res['prod_creados']} productos nuevos, {res['prod_actualizados']} actualizados, "
            f"gasto ${res['gasto']:,.2f}."
            + (f" ({res['omitidas']} órdenes ya estaban importadas)" if res['omitidas'] else ""))
        return redirect('admon_compras:historial_ordenes')


class ImportarProveedoresView(LoginRequiredMixin, View):
    """Carga masiva de proveedores desde Excel. Solo superuser."""
    def post(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        if not request.user.is_superuser:
            messages.error(request, "Solo el administrador puede hacer carga masiva.")
            return redirect('admon_compras:proveedores')

        archivo = request.FILES.get('archivo')
        if not archivo:
            messages.error(request, "Selecciona un archivo .xlsx.")
            return redirect('admon_compras:proveedores')
        if not archivo.name.lower().endswith('.xlsx'):
            messages.error(request, "El archivo debe ser .xlsx (Excel).")
            return redirect('admon_compras:proveedores')

        try:
            res = import_proveedores.importar(archivo, empresa)
        except Exception as e:
            messages.error(request, f"No se pudo procesar el archivo: {e}")
            return redirect('admon_compras:proveedores')

        messages.success(
            request, f"Carga masiva: {res['creados']} nuevos, {res['actualizados']} actualizados.")
        for err in res['errores'][:10]:
            messages.warning(request, err)
        return redirect('admon_compras:proveedores')


# --------------------------------------------------------------------------
# ÓRDENES DE COMPRA
# --------------------------------------------------------------------------
class NuevaOrdenView(LoginRequiredMixin, View):
    template_name = 'admon_compras/orden_form.html'

    def get(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        context = {
            'proveedores': proveedores_visibles(empresa, sucursal),
            'productos': Producto.objects.filter(empresa=empresa, activo=True, es_comprable=True),
            'monedas': Moneda.objects.filter(empresa=empresa, activa=True),
            'impuestos': Impuesto.objects.filter(empresa=empresa, activo=True),
            'sucursal_activa': sucursal,
            'seccion': 'compras',
        }
        return render(request, self.template_name, context)

    @transaction.atomic
    def post(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx

        productos_ids = request.POST.getlist('producto[]')
        cantidades = request.POST.getlist('cantidad[]')
        precios = request.POST.getlist('precio[]')
        ivas = request.POST.getlist('iva[]')

        if not any(productos_ids):
            messages.error(request, "La orden debe tener al menos una partida.")
            return redirect('admon_compras:nueva_orden')

        ultimo = OrdenCompra.objects.filter(
            empresa=empresa, sucursal_destino=sucursal).order_by('consecutivo').last()
        consecutivo = (ultimo.consecutivo + 1) if ultimo else 1
        anio = datetime.now().strftime('%y')
        folio = f"{sucursal.codigo_sucursal or 'OC'}-{anio}-{consecutivo:05d}"

        orden = OrdenCompra.objects.create(
            empresa=empresa, sucursal_destino=sucursal,
            proveedor_id=request.POST.get('proveedor'),
            moneda_id=request.POST.get('moneda'),
            folio=folio, consecutivo=consecutivo,
            fecha_entrega_estimada=request.POST.get('fecha_entrega') or None,
            notas=request.POST.get('notas', ''),
            estado='BORRADOR', creado_por=request.user,
        )

        _aplicar_partidas(orden, empresa, request)

        messages.success(request, f"Orden {orden.folio} creada como borrador.")
        return redirect('admon_compras:orden_detalle', pk=orden.pk)


class EditarOrdenView(LoginRequiredMixin, View):
    template_name = 'admon_compras/orden_form.html'

    def get(self, request, pk):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        orden = get_object_or_404(OrdenCompra, id=pk, empresa=empresa)
        if orden.estado not in ('BORRADOR', 'RECHAZADO'):
            messages.error(request, "Esta orden ya no se puede editar.")
            return redirect('admon_compras:orden_detalle', pk=pk)
        context = {
            'orden': orden,
            'detalles': orden.detalles.select_related('producto'),
            'proveedores': proveedores_visibles(empresa, sucursal),
            'productos': Producto.objects.filter(empresa=empresa, activo=True, es_comprable=True),
            'monedas': Moneda.objects.filter(empresa=empresa, activa=True),
            'impuestos': Impuesto.objects.filter(empresa=empresa, activo=True),
            'sucursal_activa': sucursal,
            'seccion': 'compras',
        }
        return render(request, self.template_name, context)

    @transaction.atomic
    def post(self, request, pk):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        orden = get_object_or_404(OrdenCompra, id=pk, empresa=empresa)
        if orden.estado not in ('BORRADOR', 'RECHAZADO'):
            messages.error(request, "Esta orden ya no se puede editar.")
            return redirect('admon_compras:orden_detalle', pk=pk)

        orden.proveedor_id = request.POST.get('proveedor')
        orden.moneda_id = request.POST.get('moneda')
        orden.notas = request.POST.get('notas', '')
        orden.fecha_entrega_estimada = request.POST.get('fecha_entrega') or None
        orden.save()

        _aplicar_partidas(orden, empresa, request)
        messages.success(request, f"Orden {orden.folio} actualizada.")
        return redirect('admon_compras:orden_detalle', pk=orden.pk)


class HistorialOrdenesView(LoginRequiredMixin, View):
    template_name = 'admon_compras/historial_ordenes.html'

    def get(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx

        qs = OrdenCompra.objects.filter(
            empresa=empresa, sucursal_destino=sucursal
        ).select_related('proveedor', 'moneda', 'creado_por', 'autorizador_actual')

        # --- Filtros (corren en SQL sobre TODA la tabla, no la página) ---
        q = (request.GET.get('q') or '').strip()
        f_estado = (request.GET.get('estado') or '').strip()
        f_prov = (request.GET.get('proveedor') or '').strip()
        f_desde = (request.GET.get('desde') or '').strip()
        f_hasta = (request.GET.get('hasta') or '').strip()
        f_personal = (request.GET.get('personal') or '').strip()  # '', 'si', 'no'

        if q:
            from django.db.models import Exists, OuterRef
            det = DetalleOrdenCompra.objects.filter(orden=OuterRef('pk')).filter(
                Q(producto__sku__icontains=q) | Q(producto__nombre__icontains=q)
                | Q(producto__codigo_barras__icontains=q))
            qs = qs.filter(
                Q(folio__icontains=q)
                | Q(proveedor__nombre_fiscal__icontains=q)
                | Q(proveedor__nombre_comercial__icontains=q)
                | Q(notas__icontains=q)
                | Exists(det))
        if f_estado:
            qs = qs.filter(estado=f_estado)
        if f_prov:
            qs = qs.filter(proveedor_id=f_prov)
        if f_desde:
            qs = qs.filter(fecha_emision__gte=f_desde)
        if f_hasta:
            qs = qs.filter(fecha_emision__lte=f_hasta)
        if f_personal == 'si':
            qs = qs.filter(uso_personal=True)
        elif f_personal == 'no':
            qs = qs.filter(uso_personal=False)

        # --- Sumatoria sobre el total filtrado (todas las páginas) ---
        from django.db.models import Sum, Count
        agg = qs.aggregate(n=Count('id'), subtotal=Sum('subtotal'),
                           impuestos=Sum('impuestos'), total=Sum('total'))

        # --- Paginación server-side ---
        from django.core.paginator import Paginator
        qs = qs.prefetch_related('detalles__producto')
        paginator = Paginator(qs, 25)
        page_obj = paginator.get_page(request.GET.get('page'))

        # Querystring sin 'page' para conservar filtros al paginar
        params = request.GET.copy()
        params.pop('page', None)
        querystring = params.urlencode()

        # Bandeja: OC que me toca autorizar a mí (en cualquier sucursal de la empresa)
        por_autorizar = OrdenCompra.objects.filter(
            empresa=empresa, estado='SOLICITADO', autorizador_actual=request.user
        ).select_related('proveedor', 'sucursal_destino', 'creado_por')

        context = {
            'ordenes': page_obj,
            'page_obj': page_obj,
            'totales': agg,
            'proveedores': Proveedor.objects.filter(empresa=empresa).order_by('nombre_fiscal'),
            'estados': OrdenCompra.ESTADO_CHOICES,
            'filtros': {'q': q, 'estado': f_estado, 'proveedor': f_prov,
                        'desde': f_desde, 'hasta': f_hasta, 'personal': f_personal},
            'querystring': querystring,
            'por_autorizar': por_autorizar,
            'sucursal_activa': sucursal,
            'seccion': 'compras',
        }
        return render(request, self.template_name, context)


class OrdenDetalleView(LoginRequiredMixin, View):
    template_name = 'admon_compras/orden_detalle.html'

    def get(self, request, pk):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        orden = get_object_or_404(
            OrdenCompra.objects.select_related('proveedor', 'moneda', 'creado_por', 'autorizador_actual'),
            id=pk, empresa=empresa)

        cadena = []
        if orden.estado in ('BORRADOR', 'RECHAZADO'):
            cadena = services.previsualizar_cadena(empresa, orden.creado_por, orden.total)

        context = {
            'orden': orden,
            'detalles': orden.detalles.select_related('producto', 'producto__unidad_medida'),
            'autorizaciones': orden.autorizaciones.select_related('usuario'),
            'cadena': cadena,
            'puedo_autorizar': (orden.estado == 'SOLICITADO' and orden.autorizador_actual_id == request.user.id),
            'soy_creador': orden.creado_por_id == request.user.id,
            'puede_recibir': orden.estado in ('AUTORIZADO', 'RECIBIDO'),
            'sucursal_activa': sucursal,
            'seccion': 'compras',
        }
        return render(request, self.template_name, context)

    def post(self, request, pk):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        orden = get_object_or_404(OrdenCompra, id=pk, empresa=empresa)
        accion = request.POST.get('accion')

        try:
            if accion == 'solicitar':
                services.solicitar_autorizacion(orden, request.user)
                if orden.estado == 'AUTORIZADO':
                    messages.success(request, f"{orden.folio} quedó autorizada (dentro de tu límite).")
                else:
                    messages.success(request, f"{orden.folio} enviada a {orden.autorizador_actual.get_full_name() or orden.autorizador_actual.username} para autorización.")
            elif accion == 'aprobar':
                services.aprobar(orden, request.user, request.POST.get('comentario'))
                if orden.estado == 'AUTORIZADO':
                    messages.success(request, f"{orden.folio} autorizada.")
                else:
                    messages.success(request, f"Firmaste {orden.folio}; escala a {orden.autorizador_actual.get_full_name() or orden.autorizador_actual.username}.")
            elif accion == 'rechazar':
                services.rechazar(orden, request.user, request.POST.get('motivo'))
                messages.info(request, f"{orden.folio} rechazada.")
            elif accion == 'cancelar' and orden.estado not in ('FINALIZADO', 'CANCELADO'):
                orden.estado = 'CANCELADO'
                orden.fecha_cancelacion = timezone.now()
                orden.usuario_cancelacion = request.user
                orden.motivo_cancelacion = request.POST.get('motivo')
                orden.autorizador_actual = None
                orden.save()
                messages.info(request, f"{orden.folio} cancelada.")
            elif accion == 'cancelar_revertir':
                from django.db import transaction as _tx
                from admon_inventarios.models import MovimientoInventario
                from admon_inventarios.services import registrar_movimiento, StockInsuficiente
                from admon_finanzas.models import FacturaProveedor
                if orden.estado == 'CANCELADO':
                    messages.info(request, f"{orden.folio} ya estaba cancelada.")
                else:
                    with _tx.atomic():
                        revertidos = 0
                        no_revertidos = 0
                        movs = MovimientoInventario.objects.filter(
                            empresa=empresa, referencia=orden.folio, tipo='ENTRADA')
                        for m in movs:
                            try:
                                registrar_movimiento(
                                    empresa=empresa, sucursal=m.sucursal, producto=m.producto,
                                    ubicacion=m.ubicacion, tipo='AJUSTE_NEG', origen='AJUSTE',
                                    cantidad=m.cantidad, usuario=request.user, lote=m.lote, serie=m.serie,
                                    referencia=f"CANCEL {orden.folio}", costo_unitario=m.costo_unitario,
                                    propiedad=m.propiedad, consignante=m.consignante)
                                revertidos += 1
                            except StockInsuficiente:
                                no_revertidos += 1
                        # Cancela CxP y borra sus egresos
                        for fp in FacturaProveedor.objects.filter(orden_compra=orden):
                            for ap in fp.aplicaciones.all():
                                pago = ap.pago
                                ap.delete()
                                if not pago.aplicaciones.exists():
                                    pago.delete()
                            fp.estado = 'CANCELADA'
                            fp.save(update_fields=['estado'])
                        orden.estado = 'CANCELADO'
                        orden.fecha_cancelacion = timezone.now()
                        orden.usuario_cancelacion = request.user
                        orden.motivo_cancelacion = request.POST.get('motivo') or 'Cancelación con reversa'
                        orden.save()
                    msg = f"{orden.folio} cancelada: {revertidos} líneas revertidas de inventario, CxP/egreso cancelados."
                    if no_revertidos:
                        msg += f" {no_revertidos} no se pudieron revertir (ya se vendieron)."
                    messages.info(request, msg)
            elif accion == 'toggle_personal':
                orden.uso_personal = not orden.uso_personal
                orden.save(update_fields=['uso_personal'])
                # Sus productos no se venden (uso personal); al revertir, se reactivan
                from admon_inventarios.models import Producto
                pids = orden.detalles.values_list('producto_id', flat=True)
                Producto.objects.filter(id__in=pids).update(es_vendible=not orden.uso_personal)
                if orden.uso_personal:
                    messages.info(request, f"{orden.folio} marcada como uso personal: excluida de reportes y sus productos quedan no vendibles.")
                else:
                    messages.success(request, f"{orden.folio} ya no es uso personal: vuelve a contar en reportes y sus productos son vendibles.")
            else:
                messages.error(request, "Acción no válida para el estado actual.")
        except services.ErrorAutorizacion as e:
            messages.error(request, str(e))

        return redirect('admon_compras:orden_detalle', pk=pk)


class OrdenPDFView(LoginRequiredMixin, View):
    def get(self, request, pk):
        if not request.empresa:
            return redirect('home')
        orden = get_object_or_404(OrdenCompra, id=pk, empresa=request.empresa)
        template = get_template('admon_compras/orden_pdf.html')
        html = template.render({
            'orden': orden,
            'empresa': request.empresa,
            'detalles': orden.detalles.select_related('producto'),
        })
        from xhtml2pdf import pisa
        result = io.BytesIO()
        pdf = pisa.pisaDocument(io.BytesIO(html.encode("UTF-8")), result)
        if not pdf.err:
            resp = HttpResponse(result.getvalue(), content_type='application/pdf')
            resp['Content-Disposition'] = f'inline; filename="OC-{orden.folio}.pdf"'
            return resp
        return HttpResponse("Error al generar el PDF", status=400)


# --------------------------------------------------------------------------
# CONFIGURACIÓN: cadena de autorizadores (solo matriz/dueño)
# --------------------------------------------------------------------------
class AutorizadoresView(LoginRequiredMixin, View):
    template_name = 'admon_compras/autorizadores.html'

    def get(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        if not _es_admin(request):
            messages.error(request, "Solo la matriz o el dueño configuran la cadena de autorización.")
            return redirect('admon_compras:proveedores')

        context = {
            'autorizadores': AutorizadorCompra.objects.filter(empresa=empresa).select_related('usuario', 'supervisor'),
            'form': AutorizadorCompraForm(empresa=empresa),
            'sucursal_activa': sucursal,
            'seccion': 'compras',
        }
        return render(request, self.template_name, context)

    def post(self, request):
        ctx = _contexto(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        if not _es_admin(request):
            messages.error(request, "Sin permiso para esta acción.")
            return redirect('admon_compras:proveedores')

        action = request.POST.get('action')
        if action == 'delete':
            AutorizadorCompra.objects.filter(id=request.POST.get('item_id'), empresa=empresa).delete()
            messages.success(request, "Autorizador eliminado.")
            return redirect('admon_compras:autorizadores')

        item_id = request.POST.get('item_id')
        instance = AutorizadorCompra.objects.filter(id=item_id, empresa=empresa).first() if item_id else None
        # Permitir editar por usuario ya existente
        if not instance:
            instance = AutorizadorCompra.objects.filter(
                empresa=empresa, usuario_id=request.POST.get('usuario')).first()
        form = AutorizadorCompraForm(request.POST, instance=instance, empresa=empresa)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.empresa = empresa
            obj.save()
            messages.success(request, "Autorizador guardado.")
        else:
            messages.error(request, f"Error: {form.errors.as_text()}")
        return redirect('admon_compras:autorizadores')
