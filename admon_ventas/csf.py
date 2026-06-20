"""Lectura de la Constancia de Situación Fiscal (SAT) en PDF.

Extrae, en lo posible, RFC, razón social, código postal, régimen fiscal y
domicilio. Si el PDF no tiene texto (escaneado/imagen), devuelve dict vacío
y la captura se hace manual.
"""
import re


def _texto_pdf(fileobj):
    """Devuelve el texto del PDF (o '' si no se puede leer)."""
    try:
        from pypdf import PdfReader
        fileobj.seek(0)
        reader = PdfReader(fileobj)
        partes = []
        for page in reader.pages:
            partes.append(page.extract_text() or '')
        texto = "\n".join(partes)
        # Repara mojibake (UTF-8 mal decodificado como Latin-1: "Ã³" -> "ó")
        if 'Ã' in texto or 'Â' in texto:
            try:
                texto = texto.encode('latin-1').decode('utf-8')
            except (UnicodeDecodeError, UnicodeEncodeError):
                pass
        return texto
    except Exception:
        return ''


def _buscar(patron, texto, grupo=1, flags=re.I):
    m = re.search(patron, texto, flags)
    return (m.group(grupo).strip() if m else '')


def parse_csf(fileobj):
    """Analiza la CSF. Devuelve dict con claves:
    rfc, nombre_fiscal, codigo_postal, regimen_fiscal, direccion, ok, texto_ok.
    'ok' = se extrajo al menos RFC o nombre. 'texto_ok' = el PDF traía texto.
    """
    texto = _texto_pdf(fileobj)
    res = {'rfc': '', 'nombre_fiscal': '', 'codigo_postal': '',
           'regimen_fiscal': '', 'direccion': '', 'ok': False, 'texto_ok': bool(texto.strip())}
    if not texto.strip():
        return res

    # Normaliza espacios pero conserva saltos de línea para algunos campos
    t = re.sub(r'[ \t]+', ' ', texto)

    # RFC (12 morales / 13 físicas)
    rfc = _buscar(r'RFC[:\s]*([A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3})', t)
    if not rfc:
        rfc = _buscar(r'\b([A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3})\b', t)
    res['rfc'] = rfc.upper()

    # Razón social (moral) o nombre completo (física)
    razon = _buscar(r'Denominaci[oó]n/?\s*Raz[oó]n Social[:\s]*([^\n]+)', t)
    if not razon:
        nombre = _buscar(r'Nombre\s*\(s\)[:\s]*([^\n]+)', t)
        ap1 = _buscar(r'Primer Apellido[:\s]*([^\n]+)', t)
        ap2 = _buscar(r'Segundo Apellido[:\s]*([^\n]+)', t)
        razon = ' '.join(p for p in [nombre, ap1, ap2] if p).strip()
    # Limpia colas tipo "Régimen Capital ..." si quedaron pegadas
    razon = re.split(r'\s+(?:R[eé]gimen|Fecha|CURP)\b', razon)[0].strip()
    res['nombre_fiscal'] = razon

    # Código postal
    res['codigo_postal'] = _buscar(r'C[oó]digo Postal[:\s]*([0-9]{4,5})', t)

    # Régimen fiscal (toma el primero listado)
    reg = _buscar(r'R[eé]gimen[:\s]*((?:R[eé]gimen|General|Simplificado|Sueldos|Incorporaci[oó]n|'
                  r'Actividades|Personas|Arrendamiento|Demás|Plataformas)[^\n]+)', t)
    if not reg:
        reg = _buscar(r'(R[eé]gimen General de Ley Personas Morales|'
                      r'R[eé]gimen Simplificado de Confianza|'
                      r'Sueldos y Salarios[^\n]*|'
                      r'R[eé]gimen de Actividades Empresariales[^\n]*)', t, grupo=1)
    res['regimen_fiscal'] = reg.strip()

    # Domicilio: arma con las piezas típicas de la CSF
    vial = _buscar(r'Nombre de Vialidad[:\s]*([^\n]+)', t) or _buscar(r'Nombre Vialidad[:\s]*([^\n]+)', t)
    next = _buscar(r'N[uú]mero Exterior[:\s]*([^\n]+)', t)
    nint = _buscar(r'N[uú]mero Interior[:\s]*([^\n]+)', t)
    col = _buscar(r'Nombre de la Colonia[:\s]*([^\n]+)', t)
    mun = _buscar(r'Nombre del Municipio[^:]*[:\s]*([^\n]+)', t)
    edo = _buscar(r'Nombre de la Entidad Federativa[:\s]*([^\n]+)', t)
    piezas = []
    if vial:
        calle = vial
        if next:
            calle += f' {next}'
        if nint:
            calle += f' Int. {nint}'
        piezas.append(calle)
    for p in (col, mun, edo):
        if p:
            piezas.append(p)
    if res['codigo_postal']:
        piezas.append(f"C.P. {res['codigo_postal']}")
    res['direccion'] = ', '.join(piezas)

    res['ok'] = bool(res['rfc'] or res['nombre_fiscal'])
    return res
