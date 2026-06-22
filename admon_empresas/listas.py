"""Utilidades reutilizables para listas del sistema:
búsqueda avanzada (encabezado + detalle), filtros, totales y paginación
server-side, además de exportación a Excel (CSV) del resultado filtrado.

Todo corre en la base de datos sobre el queryset completo (no la página),
así una lista con miles de registros sigue siendo rápida.
"""
import csv

from django.core.paginator import Paginator
from django.db.models import Q, Sum, Count, Exists, OuterRef
from django.http import HttpResponse
from django.utils import timezone

DEFAULT_PER_PAGE = 50
PER_PAGE_OPCIONES = (25, 50, 100, 200)


def aplicar_filtros(request, qs, *, search_header=(), detail_model=None,
                    detail_search=(), date_field=None, exactos=None):
    """Aplica búsqueda de texto, filtros exactos y rango de fechas a `qs`.

    - search_header: campos del encabezado para `q` (lookups icontains).
    - detail_model + detail_search: si se da, busca `q` dentro del detalle vía
      EXISTS (no infla los totales). detail_model debe tener FK al objeto de qs;
      detail_search son lookups relativos a ese modelo de detalle.
    - date_field: campo de fecha para los filtros desde/hasta.
    - exactos: dict {param_GET: campo_orm} para filtros de igualdad (FK, choices).

    Devuelve (qs_filtrado, filtros_aplicados_dict).
    """
    f = {}
    q = (request.GET.get('q') or '').strip()
    f['q'] = q
    if q and (search_header or detail_search):
        cond = Q()
        for campo in search_header:
            cond |= Q(**{f'{campo}__icontains': q})
        if detail_model is not None and detail_search:
            det_cond = Q()
            for campo in detail_search:
                det_cond |= Q(**{f'{campo}__icontains': q})
            det = detail_model.objects.filter(
                **{detail_model._meta.get_field(
                    _fk_a_padre(detail_model, qs.model)).name: OuterRef('pk')}
            ).filter(det_cond)
            cond |= Exists(det)
        qs = qs.filter(cond)

    for param, campo in (exactos or {}).items():
        val = (request.GET.get(param) or '').strip()
        f[param] = val
        if val:
            qs = qs.filter(**{campo: val})

    if date_field:
        desde = (request.GET.get('desde') or '').strip()
        hasta = (request.GET.get('hasta') or '').strip()
        f['desde'] = desde
        f['hasta'] = hasta
        if desde:
            qs = qs.filter(**{f'{date_field}__gte': desde})
        if hasta:
            qs = qs.filter(**{f'{date_field}__lte': hasta})

    return qs, f


def _fk_a_padre(detail_model, padre_model):
    """Encuentra el nombre del FK del modelo de detalle hacia el padre."""
    for fld in detail_model._meta.get_fields():
        if getattr(fld, 'related_model', None) is padre_model and fld.many_to_one:
            return fld.name
    raise ValueError(f"{detail_model.__name__} no tiene FK a {padre_model.__name__}")


def totales(qs, sum_fields=()):
    """Agrega Count + Sum de los campos pedidos sobre el queryset filtrado."""
    agg_kwargs = {'n': Count('id')}
    for campo in sum_fields:
        agg_kwargs[campo] = Sum(campo)
    return qs.aggregate(**agg_kwargs)


def paginar(request, qs, default_per_page=DEFAULT_PER_PAGE):
    """Pagina server-side. Devuelve (page_obj, per_page, querystring_sin_page)."""
    try:
        per_page = int(request.GET.get('per_page') or default_per_page)
    except ValueError:
        per_page = default_per_page
    if per_page not in PER_PAGE_OPCIONES:
        per_page = default_per_page
    page_obj = Paginator(qs, per_page).get_page(request.GET.get('page'))

    params = request.GET.copy()
    params.pop('page', None)
    return page_obj, per_page, params.urlencode()


def construir(request, qs, *, placeholder='', search_header=(), detail_model=None,
              detail_search=(), date_field=None, exactos=None, filtros_ui=None,
              sum_fields=(), default_per_page=DEFAULT_PER_PAGE, clear_url='',
              export_nombre='export', export_columnas=None, export_order=None):
    """Orquesta filtros + totales + paginación + export en una sola llamada.

    Devuelve un dict para fusionar al contexto. Si trae la clave 'export', la
    vista debe retornar ese HttpResponse directamente (es la descarga CSV).

    filtros_ui: lista de dicts {name, label, tipo('select'/'date'), opciones, todos}.
    El valor seleccionado se rellena solo desde request.GET.
    """
    qs, f = aplicar_filtros(
        request, qs, search_header=search_header, detail_model=detail_model,
        detail_search=detail_search, date_field=date_field, exactos=exactos)

    agg = totales(qs, sum_fields)

    if request.GET.get('export') == 'csv' and export_columnas:
        ordenado = qs.order_by(*export_order) if export_order else qs
        return {'export': exportar_csv(ordenado, export_nombre, export_columnas)}

    page_obj, per_page, querystring = paginar(request, qs, default_per_page)

    # Rellena valor seleccionado en cada filtro UI desde el request
    ui = []
    for spec in (filtros_ui or []):
        spec = dict(spec)
        val = (request.GET.get(spec['name']) or '').strip()
        if spec.get('tipo') == 'date':
            spec['val'] = val
        else:
            spec['sel'] = val
        ui.append(spec)

    lista = {
        'placeholder': placeholder,
        'q': f.get('q', ''),
        'filtros': ui,
        'per_page': per_page,
        'per_page_opciones': PER_PAGE_OPCIONES,
        'querystring': querystring,
        'clear_url': clear_url,
    }
    return {'export': None, 'page_obj': page_obj, 'totales': agg,
            'lista': lista, 'qs': qs}


def exportar_csv(qs, nombre, columnas):
    """Exporta `qs` a CSV (Excel-friendly).

    columnas: lista de (encabezado, getter) donde getter es nombre de atributo
    o un callable(obj) -> valor.
    """
    resp = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    resp['Content-Disposition'] = (
        f'attachment; filename="{nombre}_{timezone.now():%Y%m%d_%H%M}.csv"')
    resp.write('﻿')  # BOM para acentos en Excel
    w = csv.writer(resp)
    w.writerow([c[0] for c in columnas])
    for obj in qs:
        fila = []
        for _, getter in columnas:
            if callable(getter):
                val = getter(obj)
            else:
                val = obj
                for parte in getter.split('.'):
                    val = getattr(val, parte, '')
                    if callable(val):
                        val = val()
            fila.append('' if val is None else val)
        w.writerow(fila)
    return resp
