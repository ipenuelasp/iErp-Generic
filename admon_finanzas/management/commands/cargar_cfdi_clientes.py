"""Carga CFDI emitidos (XML+PDF) y los liga a sus Cuentas por Cobrar.

Lee un directorio con subcarpetas (cada una con su XML y PDF) y/o archivos .zip.
Agrupa los CFDI por RFC del receptor (cliente) y los liga a la CxC de ese
cliente cuyo total coincide con la suma del grupo (facturación por artículo).

Idempotente: un CFDI ya ligado (mismo UUID en la misma CxC) se omite.

Uso:
    python manage.py cargar_cfdi_clientes --empresa 1 --dir "/ruta/Facturas Clientes" [--exclude legion] [--dry-run]
"""
import decimal
import glob
import io
import os
import zipfile
from xml.etree import ElementTree as ET

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

D = decimal.Decimal


def _local(t):
    return t.rsplit('}', 1)[-1]


def _find(e, n):
    for x in e.iter():
        if _local(x.tag) == n:
            return x
    return None


def _parse(data):
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None
    if _local(root.tag) != 'Comprobante':
        c = _find(root, 'Comprobante')
        if c is None:
            return None
        root = c
    a = root.attrib
    re = _find(root, 'Receptor')
    tfd = _find(root, 'TimbreFiscalDigital')
    if tfd is None or not tfd.attrib.get('UUID'):
        return None
    try:
        total = D(str(a.get('Total') or '0'))
    except Exception:
        total = D('0')
    return {
        'uuid': tfd.attrib['UUID'].upper(),
        'fecha': (a.get('Fecha') or '')[:10] or None,
        'total': total,
        'serie_folio': f"{a.get('Serie', '')}{a.get('Folio', '')}"[:60],
        'rfc_rec': (re.attrib.get('Rfc') if re is not None else '') or '',
    }


class Command(BaseCommand):
    help = "Liga CFDI emitidos (XML/PDF) a sus Cuentas por Cobrar por RFC + total."

    def add_arguments(self, parser):
        parser.add_argument('--empresa', type=int, required=True)
        parser.add_argument('--dir', required=True)
        parser.add_argument('--exclude', default='legion',
                            help="Subcadenas (coma) para excluir por nombre de archivo.")
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        from admon_empresas.models import Empresa
        from admon_finanzas.models import FacturaCliente, CfdiCliente

        try:
            empresa = Empresa.objects.get(pk=opts['empresa'])
        except Empresa.DoesNotExist:
            raise CommandError(f"No existe empresa {opts['empresa']}.")
        base = opts['dir']
        if not os.path.isdir(base):
            raise CommandError(f"No existe el directorio: {base}")
        dry = opts['dry_run']
        excludes = [s.strip().lower() for s in opts['exclude'].split(',') if s.strip()]

        # 1) Recolecta entradas únicas por UUID (carpetas primero, luego zips)
        entradas = {}  # uuid -> dict(meta, xml_bytes, pdf_bytes, label)

        def excluido(nombre):
            n = nombre.lower()
            return any(e in n for e in excludes)

        for xmlp in glob.glob(os.path.join(base, '**', '*.xml'), recursive=True):
            if excluido(xmlp):
                continue
            with open(xmlp, 'rb') as fh:
                xb = fh.read()
            meta = _parse(xb)
            if not meta or meta['uuid'] in entradas:
                continue
            pdfp = os.path.splitext(xmlp)[0] + '.pdf'
            pdfb = open(pdfp, 'rb').read() if os.path.exists(pdfp) else None
            entradas[meta['uuid']] = dict(
                meta=meta, xml=xb, pdf=pdfb,
                label=os.path.basename(os.path.dirname(xmlp)))

        for zp in glob.glob(os.path.join(base, '*.zip')):
            if excluido(zp):
                continue
            try:
                zf = zipfile.ZipFile(zp)
            except zipfile.BadZipFile:
                continue
            xmls = [n for n in zf.namelist() if n.lower().endswith('.xml')]
            for n in xmls:
                meta = _parse(zf.read(n))
                if not meta or meta['uuid'] in entradas:
                    continue
                pdfs = [p for p in zf.namelist() if p.lower().endswith('.pdf')]
                pdfb = zf.read(pdfs[0]) if pdfs else None
                entradas[meta['uuid']] = dict(
                    meta=meta, xml=zf.read(n), pdf=pdfb,
                    label=os.path.basename(zp))

        # 2) Agrupa por RFC del receptor
        grupos = {}
        for uuid, e in entradas.items():
            grupos.setdefault(e['meta']['rfc_rec'].upper(), []).append(e)

        self.stdout.write(self.style.WARNING(
            f"\n{'(DRY-RUN) ' if dry else ''}Empresa {empresa.nombre_fiscal} — "
            f"{len(entradas)} CFDI en {len(grupos)} cliente(s):\n"))

        ligados = omitidos = sin_match = 0
        for rfc, items in grupos.items():
            suma = sum((e['meta']['total'] for e in items), D('0'))
            tol = max(D('5'), (suma * D('0.005')))
            cxcs = list(FacturaCliente.objects.filter(
                empresa=empresa, cliente__rfc=rfc).exclude(estado='CANCELADA'))
            match = None
            for f in cxcs:
                if abs(f.total - suma) <= tol:
                    match = f
                    break
            if not match:
                sin_match += 1
                opciones = ', '.join(f"{f.folio}=${f.total}" for f in cxcs) or 'ninguna'
                self.stdout.write(self.style.ERROR(
                    f"  ✗ RFC {rfc}: suma ${suma} de {len(items)} CFDI — sin CxC que cuadre "
                    f"(CxC del cliente: {opciones})"))
                continue
            self.stdout.write(self.style.SUCCESS(
                f"  ✓ RFC {rfc}: {len(items)} CFDI (${suma}) → {match.folio} (${match.total})"))
            for e in items:
                m = e['meta']
                ya = CfdiCliente.objects.filter(factura=match, uuid=m['uuid']).exists()
                if ya:
                    omitidos += 1
                    self.stdout.write(f"      - {m['uuid'][:8]} ${m['total']}  (ya estaba)")
                    continue
                self.stdout.write(f"      + {m['uuid'][:8]} ${m['total']}  [{e['label'][:30]}]")
                if dry:
                    continue
                obj = CfdiCliente(
                    factura=match, uuid=m['uuid'], serie_folio=m['serie_folio'],
                    fecha=m['fecha'], total=m['total'])
                obj.archivo_xml.save(f"{m['uuid']}.xml", ContentFile(e['xml']), save=False)
                if e['pdf']:
                    obj.archivo_pdf.save(f"{m['uuid']}.pdf", ContentFile(e['pdf']), save=False)
                obj.save()
                ligados += 1

        self.stdout.write(self.style.SUCCESS(
            f"\n{'(DRY-RUN) ' if dry else ''}Ligados: {ligados} · Ya estaban: {omitidos} · "
            f"Grupos sin match: {sin_match}"))
