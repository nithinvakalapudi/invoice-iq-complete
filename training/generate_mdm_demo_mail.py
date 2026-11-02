"""Create clearly synthetic invoice/email fixtures from the local MDM master.

No network calls or email sending. The existing MDM rows and fields are kept;
four demo-only columns are added, and a byte-for-byte backup is made first.
"""
from __future__ import annotations

import csv
import io
import os
import re
from datetime import datetime, timezone
from decimal import Decimal
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / 'local_data' / 'MDM' / 'vendor_accounts.csv'
BACKUP = MASTER.with_name('vendor_accounts.before_demo_2026-10-09.csv')
DEMO = ROOT / 'local_data' / 'generated_demo_2026-10-09'
OUTLOOK = ROOT / 'config' / 'local_data' / 'Outlook'
EXTRA_COLUMNS = ('Vendor Region', 'Vendor Address', 'Service Specification', 'Vendor Email')
LOCATIONS = {
    'APAC': ('Singapore', '10 Market Street, Singapore 048940'),
    'EMEA': ('London, United Kingdom', '10 Market Street, London, United Kingdom'),
    'North America': ('New York, NY', '10 Market Street, New York, NY 10001'),
    'LATAM': ('Sao Paulo, Brazil', '10 Market Street, Sao Paulo, Brazil'),
}
SERVICES = (
    ('Data access and support', 'Monthly reporting service'),
    ('Platform subscription', 'Technical support service'),
    ('Managed analytics', 'Data delivery service'),
    ('Cloud operations', 'Maintenance and support'),
)


def _email_for(vendor: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', vendor.casefold()).strip('-')
    return f'billing@{slug}.example.com'


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(buffer.getvalue(), encoding='utf-8', newline='')
    os.replace(temporary, path)


def enrich_master() -> list[dict[str, str]]:
    raw = MASTER.read_bytes()
    with io.StringIO(raw.decode('utf-8-sig'), newline='') as stream:
        reader = csv.DictReader(stream)
        columns = list(reader.fieldnames or [])
        rows = list(reader)
    if not {'Account', 'Vendor', 'Restricted To', 'Default Currency'}.issubset(columns):
        raise ValueError('Vendor Accounts master has unexpected columns')
    if not BACKUP.exists():
        BACKUP.write_bytes(raw)
    for row in rows:
        region, address = LOCATIONS.get(row['Restricted To'], ('', ''))
        suffix = int(row['Account'].rsplit('-', 1)[-1])
        services = SERVICES[(suffix - 1) % len(SERVICES)]
        row.update({
            'Vendor Region': region,
            'Vendor Address': address,
            'Service Specification': '; '.join(services),
            'Vendor Email': _email_for(row['Vendor']),
        })
    _write_csv(MASTER, columns + [col for col in EXTRA_COLUMNS if col not in columns], rows)
    return rows


def _draw(pdf: canvas.Canvas, x: float, y: float, value: str,
          size: int = 10, color: str = '#202C3A', bold: bool = False) -> None:
    font = 'Helvetica-Bold' if bold else 'Helvetica'
    pdf.setFont(font, size)
    pdf.setFillColor(HexColor(color))
    pdf.drawString(x, y, value)


def make_pdf(row: dict[str, str], index: int, output: Path) -> dict[str, str]:
    invoice_number = f'DEMO-20261009-{row["Account"].rsplit("-", 1)[-1]}'
    services = row['Service Specification'].split('; ')
    quantity = ('1', '2')
    rate = (Decimal(1200 + index * 75), Decimal(275 + index * 20))
    amounts = (rate[0], rate[1] * 2)
    net = sum(amounts)
    width, height = A4
    pdf = canvas.Canvas(str(output), pagesize=A4, pageCompression=1)
    pdf.setTitle(f'SYNTHETIC TEST INVOICE {invoice_number}')
    _draw(pdf, 42, height - 48, 'SYNTHETIC TEST INVOICE', 18, '#135992', True)
    _draw(pdf, 42, height - 71, 'Demo data only - not payable and not for external delivery.', 9, '#8C4214')
    _draw(pdf, 42, height - 108, f'Vendor: {row["Vendor"]}', 12, bold=True)
    _draw(pdf, 42, height - 127, row['Vendor Address'])
    _draw(pdf, 42, height - 146, f'Vendor Email: {row["Vendor Email"]}')
    _draw(pdf, 42, height - 182, 'Bill To: Demo Accounts Payable Department', 10, bold=True)
    _draw(pdf, 42, height - 200, '100 Example Plaza, Test City, NY 10001')
    info = [
        f'Invoice Number: {invoice_number}',
        'Invoice Date: 10/09/2026',
        f'Billing Account: {row["Account"]}',
        f'Contract ID: {row["Account"]}',
        f'Currency: {row["Default Currency"]}',
        'Service Start Date: 10/01/2026',
        'Service End Date: 10/31/2026',
    ]
    for offset, value in enumerate(info):
        _draw(pdf, 42, height - 244 - offset * 19, value)
    _draw(pdf, 42, height - 400, 'Service Period   Description   Qty   Rate / Unit   Amount', 10, '#135992', True)
    for n, description in enumerate(services):
        line = (f'10/01/2026 - 10/31/2026  {description}  {quantity[n]}  '
                f'{rate[n]:.2f}  {amounts[n]:.2f}')
        if stringWidth(line, 'Helvetica', 9) > width - 84:
            raise ValueError(f'Service line too wide: {line}')
        _draw(pdf, 42, height - 427 - n * 23, line, 9)
    _draw(pdf, 42, height - 507, f'Subtotal: {net:.2f}', 11, bold=True)
    _draw(pdf, 42, height - 529, 'Tax Amount: 0.00', 11)
    _draw(pdf, 42, height - 551, f'Total Amount Due: {net:.2f}', 12, '#135992', True)
    _draw(pdf, 42, height - 598, 'Payment Terms: Due Upon Receipt', 9)
    _draw(pdf, 42, 45, 'Generated locally from the Vendor Accounts demo master. Do not pay.', 8, '#697586')
    pdf.save()
    return {'invoice_number': invoice_number, 'net': f'{net:.2f}', 'currency': row['Default Currency']}


def make_email(row: dict[str, str], invoice: dict[str, str], pdf_path: Path,
               email_path: Path) -> None:
    message = EmailMessage()
    message['From'] = f'{row["Vendor"]} Billing <{row["Vendor Email"]}>'
    message['To'] = 'Demo Accounts Payable <ap@invoice-demo.example.com>'
    message['Date'] = format_datetime(datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc))
    message['Subject'] = f'SYNTHETIC TEST invoice {invoice["invoice_number"]} - {row["Vendor"]}'
    message['Message-ID'] = f'<{invoice["invoice_number"].casefold()}@invoice-demo.example.com>'
    message.set_content(
        f'Hello Accounts Payable,\n\nAttached is a synthetic test invoice for '
        f'{row["Vendor"]}.\nInvoice: {invoice["invoice_number"]}\n'
        f'Billing account: {row["Account"]}\nVendor region: {row["Vendor Region"]}\n'
        f'Service: {row["Service Specification"]}\n'
        f'Amount: {invoice["currency"]} {invoice["net"]}\n\n'
        'This is demo data for testing only. Do not pay or send externally.\n'
    )
    message.add_attachment(pdf_path.read_bytes(), maintype='application', subtype='pdf',
                           filename=pdf_path.name)
    email_path.write_bytes(message.as_bytes())


def generate(count: int = 10) -> list[dict[str, str]]:
    rows = enrich_master()
    selected = [row for row in rows if row.get('Status') == 'Active'
                and row.get('Vendor Address') and row.get('Default Currency')][:count]
    if len(selected) != count:
        raise ValueError(f'Only {len(selected)} eligible MDM rows found')
    invoices = DEMO / 'invoices'
    invoices.mkdir(parents=True, exist_ok=True)
    OUTLOOK.mkdir(parents=True, exist_ok=True)
    manifest = []
    for index, row in enumerate(selected, 1):
        filename = f'demo_invoice_{row["Account"]}.pdf'
        pdf_path = invoices / filename
        email_path = OUTLOOK / f'demo_mail_{row["Account"]}.eml'
        if pdf_path.exists() or email_path.exists():
            raise FileExistsError(f'Demo output already exists for {row["Account"]}')
        invoice = make_pdf(row, index, pdf_path)
        make_email(row, invoice, pdf_path, email_path)
        manifest.append({
            'Account': row['Account'], 'Vendor': row['Vendor'],
            'Vendor Region': row['Vendor Region'], 'Vendor Address': row['Vendor Address'],
            'Service Specification': row['Service Specification'],
            'Vendor Email': row['Vendor Email'], 'Invoice Number': invoice['invoice_number'],
            'Currency': invoice['currency'], 'Net Amount': invoice['net'], 'Tax Amount': '0.00',
            'PDF': str(pdf_path), 'Email': str(email_path),
        })
    _write_csv(DEMO / 'manifest.csv', list(manifest[0]), manifest)
    return manifest


if __name__ == '__main__':
    for item in generate():
        print(item['Invoice Number'], item['Vendor'], item['Account'])
