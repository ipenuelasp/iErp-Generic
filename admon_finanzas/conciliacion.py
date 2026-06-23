"""Conciliación de CFDI del SAT contra el sistema.

Lee XML de CFDI (3.3 / 4.0), extrae su metadata y la compara con las CxC
(ventas emitidas), CxP y Gastos (compras/gastos recibidos) ya capturados.
"""
import decimal
import io
import zipfile
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET

D = decimal.Decimal


def _local(tag):
    """Devuelve el nombre local de una etiqueta sin su namespace."""
    return tag.rsplit('}', 1)[-1]


def _buscar(elem, nombre):
    """Primer descendiente cuyo nombre local sea `nombre` (sin namespace)."""
    for e in elem.iter():
        if _local(e.tag) == nombre:
            return e
    return None


def _num(s):
    try:
        return D(str(s).replace(',', '').strip() or '0').quantize(D('0.01'))
    except Exception:
        return D('0')


def _fecha(s):
    s = (s or '').strip()[:10]
    for f in ('%Y-%m-%d',):
        try:
            return datetime.strptime(s, f).date()
        except Exception:
            pass
    return None


def parse_cfdi(xml_bytes):
    """Extrae metadata de un XML de CFDI. Devuelve dict o None si no es CFDI."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None
    if _local(root.tag) != 'Comprobante':
        # A veces el root trae otro envoltorio; buscar el Comprobante
        comp = _buscar(root, 'Comprobante')
        if comp is None:
            return None
        root = comp

    a = root.attrib
    emisor = _buscar(root, 'Emisor')
    receptor = _buscar(root, 'Receptor')
    tfd = _buscar(root, 'TimbreFiscalDigital')
    if tfd is None or not tfd.attrib.get('UUID'):
        return None

    # IVA trasladado total (si viene)
    iva = D('0')
    imp = _buscar(root, 'Impuestos')
    if imp is not None and imp.attrib.get('TotalImpuestosTrasladados'):
        iva = _num(imp.attrib['TotalImpuestosTrasladados'])

    return {
        'uuid': tfd.attrib['UUID'].upper(),
        'tipo': (a.get('TipoDeComprobante') or '').upper()[:2],
        'fecha': _fecha(a.get('Fecha')),
        'subtotal': _num(a.get('SubTotal')),
        'iva': iva,
        'total': _num(a.get('Total')),
        'serie_folio': f"{a.get('Serie', '')}{a.get('Folio', '')}"[:60],
        'rfc_emisor': (emisor.attrib.get('Rfc') if emisor is not None else '') or '',
        'nombre_emisor': (emisor.attrib.get('Nombre') if emisor is not None else '') or '',
        'rfc_receptor': (receptor.attrib.get('Rfc') if receptor is not None else '') or '',
        'nombre_receptor': (receptor.attrib.get('Nombre') if receptor is not None else '') or '',
    }


def iter_xmls(archivo):
    """Itera (nombre, bytes) de un archivo subido: .xml o .zip con varios XML."""
    nombre = (getattr(archivo, 'name', '') or '').lower()
    data = archivo.read()
    if nombre.endswith('.zip') or data[:2] == b'PK':
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for n in z.namelist():
                if n.lower().endswith('.xml'):
                    yield n, z.read(n)
    else:
        yield nombre, data


def cargar_comprobantes(archivos, empresa):
    """Procesa los archivos subidos y guarda/actualiza ComprobanteSAT.
    Devuelve resumen dict. Clasifica por RFC de la empresa."""
    from .models import ComprobanteSAT
    rfc_empresa = (empresa.rfc or '').upper().strip()
    res = dict(leidos=0, emitidos=0, recibidos=0, ajenos=0, no_cfdi=0, nuevos=0)
    for archivo in archivos:
        for _n, xb in iter_xmls(archivo):
            meta = parse_cfdi(xb)
            if not meta:
                res['no_cfdi'] += 1
                continue
            res['leidos'] += 1
            if meta['rfc_emisor'].upper() == rfc_empresa:
                direccion = 'EMITIDO'; res['emitidos'] += 1
            elif meta['rfc_receptor'].upper() == rfc_empresa:
                direccion = 'RECIBIDO'; res['recibidos'] += 1
            else:
                res['ajenos'] += 1
                continue
            _obj, creado = ComprobanteSAT.objects.update_or_create(
                empresa=empresa, uuid=meta['uuid'],
                defaults=dict(direccion=direccion, tipo=meta['tipo'], fecha=meta['fecha'],
                              rfc_emisor=meta['rfc_emisor'], nombre_emisor=meta['nombre_emisor'],
                              rfc_receptor=meta['rfc_receptor'], nombre_receptor=meta['nombre_receptor'],
                              subtotal=meta['subtotal'], iva=meta['iva'], total=meta['total'],
                              serie_folio=meta['serie_folio']))
            if creado:
                res['nuevos'] += 1
    return res


def conciliar(empresa):
    """Compara los ComprobanteSAT con CxC / CxP / Gastos. Devuelve filas con
    estado: CONCILIADO, SIN_UUID (match por monto+fecha, falta capturar UUID),
    FALTANTE (no está en el sistema)."""
    from .models import ComprobanteSAT, FacturaCliente, FacturaProveedor, Gasto

    comps = list(ComprobanteSAT.objects.filter(empresa=empresa))

    # Índices por UUID
    cxc_uuid = {f.uuid_cfdi.upper(): f for f in FacturaCliente.objects.filter(
        empresa=empresa).exclude(uuid_cfdi__isnull=True).exclude(uuid_cfdi='') if f.uuid_cfdi}
    cxp_uuid = {f.uuid_cfdi.upper(): f for f in FacturaProveedor.objects.filter(
        empresa=empresa).exclude(uuid_cfdi__isnull=True).exclude(uuid_cfdi='') if f.uuid_cfdi}
    gasto_uuid = {g.uuid_cfdi.upper(): g for g in Gasto.objects.filter(
        empresa=empresa).exclude(uuid_cfdi__isnull=True).exclude(uuid_cfdi='') if g.uuid_cfdi}

    filas = []
    for c in comps:
        estado = 'FALTANTE'; doc = None; doc_tipo = ''
        if c.direccion == 'EMITIDO':
            if c.uuid in cxc_uuid:
                estado = 'CONCILIADO'; doc = cxc_uuid[c.uuid]; doc_tipo = 'CxC'
            else:
                # match por total+fecha (CxC sin UUID)
                cand = FacturaClienteCand(empresa, c)
                if cand:
                    estado = 'SIN_UUID'; doc = cand; doc_tipo = 'CxC'
        else:  # RECIBIDO
            if c.uuid in cxp_uuid:
                estado = 'CONCILIADO'; doc = cxp_uuid[c.uuid]; doc_tipo = 'CxP'
            elif c.uuid in gasto_uuid:
                estado = 'CONCILIADO'; doc = gasto_uuid[c.uuid]; doc_tipo = 'Gasto'
            else:
                cand = FacturaProvCand(empresa, c) or GastoCand(empresa, c)
                if cand:
                    estado = 'SIN_UUID'; doc = cand[0]; doc_tipo = cand[1]
        filas.append({'comp': c, 'estado': estado, 'doc': doc, 'doc_tipo': doc_tipo})
    return filas


def _aprox(a, b):
    """Match si la diferencia es ≤ 2% del mayor, con mínimo de $1.
    Cubre redondeos de centavos Y descuentos/promociones de Amazon."""
    a, b = (a or D('0')), (b or D('0'))
    mayor = max(abs(a), abs(b))
    tolerancia = max(D('1.00'), (mayor * D('0.02')).quantize(D('0.01')))
    return abs(a - b) <= tolerancia


_RANGO_DIAS = 5  # tolerancia de ±5 días entre fecha del doc y fecha del CFDI


def _rango_fecha(d):
    return d - timedelta(days=_RANGO_DIAS), d + timedelta(days=_RANGO_DIAS)


def FacturaClienteCand(empresa, c):
    from .models import FacturaCliente
    f_min, f_max = _rango_fecha(c.fecha)
    for f in FacturaCliente.objects.filter(
            empresa=empresa, fecha_emision__range=(f_min, f_max)).exclude(estado='CANCELADA'):
        if (not f.uuid_cfdi) and _aprox(f.total, c.total):
            return f
    return None


def FacturaProvCand(empresa, c):
    from .models import FacturaProveedor
    f_min, f_max = _rango_fecha(c.fecha)
    for f in FacturaProveedor.objects.filter(
            empresa=empresa, fecha_emision__range=(f_min, f_max)).exclude(estado='CANCELADA'):
        if (not f.uuid_cfdi) and _aprox(f.total, c.total):
            return (f, 'CxP')
    return None


def GastoCand(empresa, c):
    from .models import Gasto
    f_min, f_max = _rango_fecha(c.fecha)
    for g in Gasto.objects.filter(empresa=empresa, fecha__range=(f_min, f_max)):
        if (not g.uuid_cfdi) and _aprox(g.total, c.total):
            return (g, 'Gasto')
    return None
