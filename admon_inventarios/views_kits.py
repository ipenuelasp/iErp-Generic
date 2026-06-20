import decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.utils import timezone

from .models import (
    Producto, Ubicacion, Existencia,
    Kit, DetalleKit, InstanciaKit, SalidaKit, ContenidoSalidaKit,
)
from .views import _contexto_valido, puede_editar_maestro
from .services import (registrar_movimiento, StockInsuficiente,
                       reabastecer_caja, ubicacion_de_caja, stock_disponible)


class KitsView(LoginRequiredMixin, View):
    """Plantillas de kits y cajas físicas (instancias)."""
    template_name = 'admon_inventarios/kits.html'

    def get(self, request):
        ctx = _contexto_valido(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx

        context = {
            'kits': Kit.objects.filter(empresa=empresa).prefetch_related(
                'componentes__producto', 'instancias__sucursal_actual'),
            'productos': Producto.objects.filter(empresa=empresa, activo=True),
            'puede_editar_maestro': puede_editar_maestro(request),
            'sucursal_activa': sucursal,
            'seccion': 'inventarios',
        }
        return render(request, self.template_name, context)

    def post(self, request):
        ctx = _contexto_valido(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        accion = request.POST.get('accion')

        if accion == 'crear_kit':
            if not puede_editar_maestro(request):
                messages.error(request, "Solo la sucursal matriz puede crear plantillas de kit.")
                return redirect('admon_inventarios:kits')

            kit = Kit.objects.create(
                empresa=empresa,
                codigo=request.POST.get('codigo'),
                nombre=request.POST.get('nombre'),
                descripcion=request.POST.get('descripcion'),
            )
            prod_ids = request.POST.getlist('producto_id[]')
            cantidades = request.POST.getlist('cantidad[]')
            retornables = request.POST.getlist('es_retornable[]')
            for i, pid in enumerate(prod_ids):
                cant = decimal.Decimal(cantidades[i] or '0')
                if pid and cant > 0:
                    DetalleKit.objects.create(
                        kit=kit,
                        producto=get_object_or_404(Producto, id=pid, empresa=empresa),
                        cantidad_requerida=cant,
                        es_retornable=(retornables[i] == '1') if i < len(retornables) else False,
                    )
            messages.success(request, f"Kit '{kit.nombre}' creado.")

        elif accion == 'crear_caja':
            kit = get_object_or_404(Kit, id=request.POST.get('kit_id'), empresa=empresa)
            InstanciaKit.objects.create(
                empresa=empresa,
                kit=kit,
                codigo_caja=request.POST.get('codigo_caja'),
                sucursal_actual=sucursal,
            )
            messages.success(request, f"Caja '{request.POST.get('codigo_caja')}' registrada en {sucursal.nombre}.")

        elif accion == 'eliminar_kit':
            if not puede_editar_maestro(request):
                messages.error(request, "Solo la sucursal matriz puede eliminar plantillas.")
                return redirect('admon_inventarios:kits')
            kit = get_object_or_404(Kit, id=request.POST.get('kit_id'), empresa=empresa)
            if kit.instancias.exists():
                kit.activo = False
                kit.save()
                messages.info(request, "El kit tiene cajas registradas: se desactivó en lugar de eliminarse.")
            else:
                kit.delete()
                messages.success(request, "Kit eliminado.")

        return redirect('admon_inventarios:kits')


class SalidasKitView(LoginRequiredMixin, View):
    template_name = 'admon_inventarios/salidas_kit.html'

    def get(self, request):
        ctx = _contexto_valido(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx

        context = {
            'salidas': SalidaKit.objects.filter(empresa=empresa, sucursal_origen=sucursal).select_related(
                'instancia_kit__kit', 'creado_por'),
            'cajas_disponibles': InstanciaKit.objects.filter(
                sucursal_actual=sucursal, estado='DISPONIBLE', kit__activo=True).select_related('kit'),
            'sucursal_activa': sucursal,
            'seccion': 'inventarios',
        }
        return render(request, self.template_name, context)

    def post(self, request):
        """Crear salida (en estado PREPARANDO)."""
        ctx = _contexto_valido(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx

        caja = get_object_or_404(
            InstanciaKit, id=request.POST.get('instancia_kit'),
            sucursal_actual=sucursal, estado='DISPONIBLE')

        salida = SalidaKit.objects.create(
            empresa=empresa,
            instancia_kit=caja,
            sucursal_origen=sucursal,
            hospital_cliente=request.POST.get('hospital'),
            doctor_responsable=request.POST.get('doctor'),
            numero_cirugia=request.POST.get('cirugia'),
            fecha_retorno_esperada=request.POST.get('retorno_esperado') or None,
            creado_por=request.user,
            notas=request.POST.get('notas'),
        )
        caja.estado = 'EN_PREPARACION'
        caja.save()
        messages.success(request, f"Salida {salida.folio} creada. Ahora arma la caja.")
        return redirect('admon_inventarios:salida_kit_detalle', pk=salida.pk)


class SalidaKitDetalleView(LoginRequiredMixin, View):
    template_name = 'admon_inventarios/salida_kit_detalle.html'

    def get(self, request, pk):
        ctx = _contexto_valido(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx

        salida = get_object_or_404(
            SalidaKit.objects.select_related('instancia_kit__kit', 'creado_por'),
            pk=pk, empresa=empresa)

        # Para armar la caja: componentes de la plantilla con existencias disponibles
        componentes = []
        if salida.estado == 'PREPARANDO':
            for comp in salida.instancia_kit.kit.componentes.select_related('producto'):
                existencias = Existencia.objects.filter(
                    producto=comp.producto, sucursal=sucursal, cantidad__gt=0,
                ).select_related('ubicacion', 'ubicacion__almacen', 'lote', 'serie')
                componentes.append({'comp': comp, 'existencias': existencias})

        context = {
            'salida': salida,
            'componentes': componentes,
            'contenido': salida.contenido.select_related('producto', 'lote', 'serie', 'ubicacion_origen'),
            'sucursal_activa': sucursal,
            'seccion': 'inventarios',
        }
        return render(request, self.template_name, context)

    @transaction.atomic
    def post(self, request, pk):
        ctx = _contexto_valido(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx

        salida = get_object_or_404(SalidaKit, pk=pk, empresa=empresa, sucursal_origen=sucursal)
        accion = request.POST.get('accion')
        caja = salida.instancia_kit

        try:
            if accion == 'enviar' and salida.estado == 'PREPARANDO':
                self._procesar_envio(request, empresa, sucursal, salida)
                messages.success(request, f"{salida.folio}: caja {caja.codigo_caja} enviada a {salida.hospital_cliente}.")

            elif accion == 'retornar' and salida.estado in ('ENVIADA', 'EN_USO'):
                self._procesar_retorno(request, empresa, sucursal, salida)
                messages.success(request, f"{salida.folio}: retorno procesado. Lo usado quedó listo para facturar.")

            elif accion == 'cerrar' and salida.estado == 'RETORNADA':
                salida.estado = 'CERRADA'
                salida.save()
                caja.estado = 'DISPONIBLE'
                caja.save()
                messages.success(request, f"{salida.folio} cerrada. La caja {caja.codigo_caja} está disponible para rellenar y volver a salir.")

            elif accion == 'cancelar' and salida.estado == 'PREPARANDO':
                salida.estado = 'CANCELADA'
                salida.save()
                caja.estado = 'DISPONIBLE'
                caja.save()
                messages.info(request, f"{salida.folio} cancelada.")

            else:
                messages.error(request, "Acción no válida para el estado actual.")

        except (ValueError, StockInsuficiente) as e:
            transaction.set_rollback(True)
            messages.error(request, f"Error: {e}")

        return redirect('admon_inventarios:salida_kit_detalle', pk=pk)

    def _procesar_envio(self, request, empresa, sucursal, salida):
        """Arma la caja: baja del stock todo lo que sale al hospital.
        Regla: una caja no mezcla stock propio con consignación (ni de
        distintos consignantes); la propiedad se determina por lo que se carga."""
        kit = salida.instancia_kit.kit
        hubo_contenido = False
        propiedad_caja = None
        consignante_caja = None

        for comp in kit.componentes.select_related('producto'):
            exist_ids = request.POST.getlist(f'kit_exist_{comp.id}[]')
            cants = request.POST.getlist(f'kit_cant_{comp.id}[]')
            for j, ex_id in enumerate(exist_ids):
                cant = decimal.Decimal(cants[j] or '0')
                if not ex_id or cant <= 0:
                    continue
                existencia = get_object_or_404(
                    Existencia, id=ex_id, producto=comp.producto, sucursal=sucursal)

                # No mezclar propiedad/consignante en la misma caja
                if propiedad_caja is None:
                    propiedad_caja = existencia.propiedad
                    consignante_caja = existencia.consignante
                elif (existencia.propiedad != propiedad_caja or
                      existencia.consignante_id != (consignante_caja.id if consignante_caja else None)):
                    raise ValueError(
                        "No se puede mezclar stock propio y de consignación (o de distintos "
                        "consignantes) en la misma caja. Arma cajas separadas.")

                registrar_movimiento(
                    empresa=empresa, sucursal=sucursal, producto=comp.producto,
                    ubicacion=existencia.ubicacion, tipo='KIT_SALIDA', origen='KIT',
                    cantidad=cant, usuario=request.user,
                    lote=existencia.lote, serie=existencia.serie,
                    referencia=salida.folio,
                    propiedad=existencia.propiedad, consignante=existencia.consignante,
                )
                if existencia.serie:
                    existencia.serie.estado = 'EN_KIT'
                    existencia.serie.save()

                ContenidoSalidaKit.objects.create(
                    salida=salida, producto=comp.producto,
                    lote=existencia.lote, serie=existencia.serie,
                    ubicacion_origen=existencia.ubicacion,
                    es_retornable=comp.es_retornable,
                    propiedad=existencia.propiedad, consignante=existencia.consignante,
                    cantidad_enviada=cant,
                )
                hubo_contenido = True

        if not hubo_contenido:
            raise ValueError("La caja está vacía: captura el contenido que sale.")

        salida.propiedad = propiedad_caja or 'PROPIO'
        salida.consignante = consignante_caja
        salida.estado = 'ENVIADA'
        salida.fecha_salida = timezone.now()
        salida.save()
        salida.instancia_kit.estado = 'EN_CAMPO'
        salida.instancia_kit.save()

    def _procesar_retorno(self, request, empresa, sucursal, salida):
        """Procesa el regreso usando el servicio compartido del motor."""
        from .services import registrar_retorno_kit
        retornos = {item.id: (request.POST.get(f'ret_{item.id}') or '0')
                    for item in salida.contenido.all()}
        registrar_retorno_kit(salida=salida, retornos=retornos, usuario=request.user)


class ReabastecerCajaView(LoginRequiredMixin, View):
    """Carga una caja hasta el estándar del kit, tomando piezas del almacén."""
    template_name = 'admon_inventarios/reabastecer_caja.html'

    def get(self, request, pk):
        ctx = _contexto_valido(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        caja = get_object_or_404(InstanciaKit, id=pk, sucursal_actual=sucursal)
        ubic = ubicacion_de_caja(caja)

        # contenido actual de la caja por producto
        actual = {}
        for ex in Existencia.objects.filter(ubicacion=ubic, cantidad__gt=0):
            actual[ex.producto_id] = actual.get(ex.producto_id, 0) + ex.cantidad

        filas = []
        for prod, requerida, _ret in caja.lineas_objetivo():
            act = actual.get(prod.id, 0)
            falta = requerida - act
            filas.append({'producto': prod, 'requerida': requerida,
                          'actual': act, 'falta': falta if falta > 0 else 0,
                          'disp': stock_disponible(prod, sucursal=sucursal)})

        ubicaciones = Ubicacion.objects.filter(
            almacen__sucursal=sucursal, activa=True).exclude(almacen__codigo='CAJAS').select_related('almacen')

        total_en_caja = sum(actual.values()) if actual else 0
        return render(request, self.template_name, {
            'caja': caja, 'filas': filas, 'ubicaciones': ubicaciones,
            'total_en_caja': total_en_caja,
            'sucursal_activa': sucursal, 'seccion': 'inventarios',
        })

    def post(self, request, pk):
        ctx = _contexto_valido(request)
        if not ctx:
            return redirect('home')
        empresa, sucursal = ctx
        caja = get_object_or_404(InstanciaKit, id=pk, sucursal_actual=sucursal)
        accion = request.POST.get('accion') or 'reabastecer'
        destino = get_object_or_404(Ubicacion, id=request.POST.get('origen'), almacen__sucursal=sucursal)

        try:
            if accion == 'vaciar':
                from .services import vaciar_caja
                n = vaciar_caja(caja=caja, destino_ubicacion=destino, usuario=request.user)
                if n:
                    messages.success(request, f"Caja {caja.codigo_caja} vaciada: {n} productos regresaron al almacén.")
                else:
                    messages.info(request, f"La caja {caja.codigo_caja} ya estaba vacía.")
            else:
                cantidades = {}
                for prod, _req, _ret in caja.lineas_objetivo():
                    v = request.POST.get(f'cant_{prod.id}')
                    if v:
                        cantidades[prod.id] = v
                n = reabastecer_caja(caja=caja, origen_ubicacion=destino, cantidades=cantidades, usuario=request.user)
                messages.success(request, f"Caja {caja.codigo_caja} reabastecida ({n} productos).")
        except (ValueError, StockInsuficiente) as e:
            messages.error(request, f"Error: {e}")
        return redirect('admon_inventarios:reabastecer_caja', pk=pk)


def _salida_pdf(request, pk, template, prefijo):
    if not request.empresa:
        return redirect('home')
    import io
    from django.http import HttpResponse
    from django.template.loader import get_template
    from xhtml2pdf import pisa
    salida = get_object_or_404(
        SalidaKit.objects.select_related('instancia_kit__kit', 'cliente'),
        pk=pk, empresa=request.empresa)
    html = get_template(template).render({
        'salida': salida, 'empresa': request.empresa,
        'contenido': salida.contenido.select_related('producto', 'lote', 'serie'),
    })
    result = io.BytesIO()
    pdf = pisa.pisaDocument(io.BytesIO(html.encode('UTF-8')), result)
    if pdf.err:
        return HttpResponse("Error al generar el PDF", status=400)
    resp = HttpResponse(result.getvalue(), content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="{prefijo}-{salida.folio}.pdf"'
    return resp


class ValeSalidaPDFView(LoginRequiredMixin, View):
    """Vale / remisión: lo que va físicamente en la caja al hospital."""
    def get(self, request, pk):
        return _salida_pdf(request, pk, 'admon_inventarios/vale_salida_pdf.html', 'Vale')


class HojaConsumoPDFView(LoginRequiredMixin, View):
    """Hoja de consumo: enviado / regresado / usado, para firma del doctor."""
    def get(self, request, pk):
        return _salida_pdf(request, pk, 'admon_inventarios/hoja_consumo_pdf.html', 'Consumo')
