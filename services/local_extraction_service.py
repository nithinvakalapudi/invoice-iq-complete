"""Local PDF/OCR extraction using printed labels, tables and validation rules."""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from config.settings import settings
from services.ocr_service import extract_document_text
from utils.date_utils import normalize_date, document_date

_MONTH = r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
DATE = (rf'(?:\d{{4}}-\d{{1,2}}-\d{{1,2}}|\d{{1,2}}[/.-]\d{{1,2}}[/.-]\d{{2,4}}'
        rf'|{_MONTH}\s+\d{{1,2}},?\s+\d{{4}}|\d{{1,2}}\s+{_MONTH}\s+\d{{4}})')
MONEY = re.compile(r"(?<![\d,])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}(?!\d)")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
DATE_RE = re.compile(DATE, re.IGNORECASE)


def extraction_ready() -> bool:
    """Native PDF parsing is available without any invoice model artifact."""
    return True


def _pilot():
    """Compatibility hook for historical experiments; runtime models are disabled."""
    return None


def model_diagnostics() -> dict:
    from services.ocr_service import is_tesseract_available
    return {'ready': True, 'models_enabled': False, 'backend': 'ocr_rules',
            'ocr_available': is_tesseract_available(), 'issues': {},
            'date_order': settings.invoice_date_order, 'region_source': 'supplier_address'}


def _reviewed_model():
    return None


def _ranked_lines(lines: list[str], field: str) -> list[str]:
    # Keep this hook for old evaluation scripts, but never load weights or infer.
    return []


def _value_after_label(lines: list[str], label: str) -> list[str]:
    pattern = re.compile(label, re.IGNORECASE)
    found = []
    for index, line in enumerate(lines):
        match = pattern.search(line)
        if not match:
            continue
        same_line = line[match.end():].strip(" :#;–—-\t")
        if same_line:
            found.append(same_line)
        if index + 1 < len(lines):
            found.append(lines[index + 1])
    return found


def _first_money(candidates: list[str]) -> str | None:
    for line in candidates:
        match = MONEY.search(line)
        if match:
            return match.group().replace(",", "")
    return None


def _money_after_label(lines: list[str], label: str) -> str | None:
    """Read an amount after its label without mistaking a tax rate for tax money."""
    pattern = re.compile(label, re.IGNORECASE)
    for index, line in enumerate(lines):
        match = pattern.search(line)
        if not match:
            continue
        remainder = line[match.end():]
        if '%' in remainder:
            remainder = remainder.rsplit('%', 1)[-1]
        amount = _first_money([remainder])
        if amount:
            return amount
        if index + 1 < len(lines):
            amount = _first_money([lines[index + 1]])
            if amount:
                return amount
    return None


def _arithmetically_supported_total(lines: list[str]) -> str | None:
    """Only fill an unlabeled total when printed line amounts reconcile to it.

    The value must itself be visible in OCR. Repeated equal charge amounts are
    ambiguous (possibly distinct charges), so this conservative fallback stops.
    """
    charges: dict[Decimal, str] = {}
    for line in lines:
        amounts = [Decimal(match.group().replace(',', '')) for match in MONEY.finditer(line)]
        if not amounts or not re.search(r'[A-Za-z]{3}', line):
            continue
        if re.search(r'\b(?:total|balance|tax|discount|shipping|due|account)\b', line, re.I):
            continue
        if len(amounts) > 1 and amounts[-1] != amounts[-2]:
            continue
        charges.setdefault(amounts[-1], line)
    if len(charges) < 3:
        return None
    expected = sum(charges, Decimal('0'))
    if expected <= 0:
        return None
    printed = any(any(Decimal(match.group().replace(',', '')) == expected
                      for match in MONEY.finditer(line))
                  for line in lines if line not in charges.values())
    return format(expected, '.2f') if printed else None


def _date_from(lines: list[str], labels: str, field: str | None = None) -> str | None:
    if field == 'invoice_date':
        for index, line in enumerate(lines):
            if (re.fullmatch(r'invoice\s+date', line, re.I)
                    and any(re.fullmatch(r'invoice\s+number', earlier, re.I)
                            for earlier in lines[max(0, index - 2):index])
                    and index + 1 < len(lines)
                    and re.fullmatch(r'payment\s+due', lines[index + 1], re.I)):
                for candidate in lines[index + 2:index + 7]:
                    if re.search(r'\bbill\s+to\b', candidate, re.I):
                        break
                    match = DATE_RE.search(candidate)
                    if match and normalize_date(match.group()):
                        return match.group()
    candidates = _value_after_label(lines, labels)
    if field and field != 'invoice_date':
        candidates += _ranked_lines(lines, field)
    for line in candidates:
        match = DATE_RE.search(line)
        if match and normalize_date(match.group()):
            return match.group()
    if field == 'invoice_date':
        header_end = next((index for index, line in enumerate(lines)
                           if re.search(r'\b(?:bill\s+to|(?:service|billing|contract)\s+period|date\(s\)\s+of\s+service|for\s+service)\b', line, re.I)),
                          min(len(lines), 20))
        for line in lines[:header_end]:
            if re.search(r'\bservice\s+period\b', line, re.I):
                continue
            candidate = re.split(r'\b(?:due|terms)\b', line, maxsplit=1, flags=re.I)[0]
            match = DATE_RE.search(candidate)
            if match and normalize_date(match.group()):
                return match.group()
    return None


def _company_name(lines: list[str], kind: str) -> str | None:
    # A loose "vendor" search also matches "Vendor address", which is a
    # frequent heading in PDFs and is not the supplier's name.
    label = r"^\s*vendor\s*(?::|$)" if kind == "vendor_name" else r"\bbill\s+to\b\s*:?"
    if kind == 'customer_name' and not any(re.search(label, line, re.IGNORECASE) for line in lines):
        return None
    legal_suffix = re.compile(r"\b(?:LLC|Ltd\.?|Limited|Inc\.?|Corp\.?|GmbH|Pte\.?|PLC)\b", re.IGNORECASE)
    def clean(value: str) -> str | None:
        value = re.sub(r"^(?:Vendor|Bill\s+To)\s*:\s*", "", value, flags=re.IGNORECASE).strip()
        if value.casefold() in {'vendor', 'bill to'}:
            return None
        if re.fullmatch(r"(?:tax|service|freight\s*/\s*commercial)\s+invoice", value, re.I):
            return None
        if (3 <= len(value) <= 100 and re.search(r"[A-Za-z]", value)
                and not DATE_RE.search(value) and not MONEY.search(value)
                and not value.lower().startswith(("attn", "accounts payable", "contact", "reference", "invoice", "page "))
                and not any(word in value.casefold() for word in ("copilot", "market place", "inetcache", "outlook/"))):
            return value
        return None
    if kind == "customer_name":
        for index, line in enumerate(lines):
            if re.search(label, line, re.IGNORECASE):
                for candidate in lines[index:index + 12]:
                    value = clean(candidate)
                    if value and legal_suffix.search(value):
                        return value
                if any("SAMPLE / DEMO DOCUMENT" in item for item in lines[:5]):
                    for candidate in lines[index + 1:index + 8]:
                        value = clean(candidate)
                        if value and not re.search(r"\b(?:street|road|suite|floor)\b", value, re.IGNORECASE):
                            return value
    for candidate in _value_after_label(lines, label):
        value = clean(candidate)
        if value and not re.search(r'\b(?:street|road|suite|floor|avenue|drive)\b|\d', value, re.I):
            return value
    bill_to_index = next((i for i, line in enumerate(lines)
                          if re.search(r'\bbill\s+to\b', line, re.I)), None)
    for candidate in _ranked_lines(lines, kind):
        if kind == 'vendor_name' and bill_to_index is not None and candidate not in lines[:bill_to_index]:
            continue
        if legal_suffix.search(candidate):
            value = clean(candidate)
            if value:
                return value
    if kind == 'vendor_name':
        bill_to = next((i for i, line in enumerate(lines)
                        if re.search(r'\bbill\s+to\b', line, re.I)), None)
        if bill_to is not None:
            for candidate in lines[:bill_to]:
                if legal_suffix.search(candidate):
                    value = clean(candidate)
                    if value and not re.search(r'\b(?:street|road|suite|floor|avenue|drive)\b|\d', value, re.I):
                        return value
            for candidate in lines[:bill_to]:
                value = clean(candidate)
                if (value and not re.search(r'\d|\b(?:street|road|suite|floor|avenue|drive)\b', value, re.I)
                        and len(value.split()) >= 2):
                    return value
        first_number = next((i for i, line in enumerate(lines)
                             if re.search(r'\binvoice\s*(?:number|no\.?|#)', line, re.I)), None)
        if first_number is not None:
            for candidate in _ranked_lines(lines, kind):
                if candidate in lines[:first_number]:
                    value = clean(candidate)
                    if value and not re.search(r'\b(?:street|road|suite|floor|avenue|drive)\b|\d', value, re.I):
                        return value
    return None


def _invoice_number(lines: list[str]) -> str | None:
    candidates = _value_after_label(lines, r"\binvoice\s*(?:number|no\.?|#)\s*[:#;]?")
    candidates += _value_after_label(lines, r"\breference\s*:")
    for line in candidates + _ranked_lines(lines, "invoice_number"):
        value = re.sub(r"^(?:Invoice\s*(?:Number|No\.?|#)|Reference)\s*[:#;]?\s*",
                       "", line, flags=re.IGNORECASE).strip()
        value = re.split(r"\s+(?:Date|Terms)\s*:", value, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        if line not in candidates and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9/_-]{3,79}", value):
            continue
        explicit_reference = (line in candidates and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9/_-]{2,79}', value)
                              and value.casefold() not in {'date', 'total', 'amount', 'currency', 'vendor',
                                  'invoice', 'payment', 'service', 'billing', 'description', 'quantity'})
        if value and len(value) <= 80 and (re.search(r"\d", value) or explicit_reference) and not DATE_RE.fullmatch(value):
            return value
    for line in lines[:12]:
        match = re.fullmatch(r"(?:No\.\s*)?(INV[-_/][A-Za-z0-9/_-]{3,75})", line, re.I)
        if match:
            return match.group(1)
    return None


def _period_candidates(lines: list[str]) -> set[tuple[str, str]]:
    pattern = re.compile(rf"({DATE})\s*(?:-|–|—|to)\s*({DATE})", re.IGNORECASE)
    periods = set()
    for index, line in enumerate(lines):
        if re.search(r'\bcontract\b', line, re.I) or (index and re.fullmatch(
                r'contract\s+period\s*:?', lines[index - 1], re.I)):
            continue
        match = pattern.search(line)
        if not match:
            continue
        first, last = match.groups()
        start = document_date(first, '\n'.join(lines), settings.invoice_date_order)
        end = document_date(last, '\n'.join(lines), settings.invoice_date_order)
        if start and end and start <= end:
            periods.add((start, end))
        elif not start and not end and normalize_date(first) and normalize_date(last):
            periods.add((first, last))
    return periods


def _period(lines: list[str]) -> tuple[str | None, str | None]:
    periods = _period_candidates(lines)
    return next(iter(periods)) if len(periods) == 1 else (None, None)


def _service_lines(lines: list[str]) -> list[dict[str, str]]:
    """Parse inline and PDF cell-per-line tables without trusting bad arithmetic."""
    amount = r"(?:[A-Za-z₹€£$�]{0,3})?([\d,]+\.\d{2})"
    row = re.compile(
        rf"^({DATE})\s*(?:-|–|—|to)\s*({DATE})\s+(.+?)\s+"
        rf"(\d+(?:\.\d+)?)\s+{amount}\s*{amount}\s*$", re.I)
    period = re.compile(rf"^{DATE}(?:\s*(?:-|–|—|to)\s*{DATE})?$", re.I)
    number = re.compile(r"^\d+(?:\.\d+)?$")
    money = re.compile(rf"^{amount}$")
    items = []
    def add(description: str, quantity: str, rate: str, total: str) -> None:
        description = description.strip(' :-–—')
        if not description or not re.search(r'[A-Za-z]', description):
            return
        try:
            qty_value = Decimal(quantity)
            rate_value = Decimal(rate.replace(',', ''))
            total_value = Decimal(total.replace(',', ''))
        except (ValueError, ArithmeticError):
            return
        if qty_value <= 0 or abs(qty_value * rate_value - total_value) > Decimal('0.02'):
            return
        items.append({'description': description, 'quantity': quantity,
                      'unit_price': format(rate_value, '.2f'),
                      'line_total': format(total_value, '.2f')})

    for index, line in enumerate(lines):
        match = row.match(line)
        if match:
            _, _, description, quantity, rate, total = match.groups()
            add(description, quantity, rate, total)
        elif period.fullmatch(line) and index + 3 < len(lines):
            description, quantity, rate = lines[index + 1:index + 4]
            if not number.fullmatch(quantity):
                continue
            # PDF text extraction sometimes joins neighboring table cells:
            # "$2,702.66$2,702.66" is one line containing rate and amount.
            joined = re.fullmatch(rf"{amount}\s*{amount}", rate, re.I)
            if joined:
                add(description, quantity, joined.group(1), joined.group(2))
            elif index + 4 < len(lines):
                rate_match, total_match = money.fullmatch(rate), money.fullmatch(lines[index + 4])
                if rate_match and total_match:
                    add(description, quantity, rate_match.group(1), total_match.group(1))
    if not items:
        # A common invoice table has no service-period column. Its PDF text
        # often appears as one cell per line under DESCRIPTION/QTY/UNIT PRICE/AMOUNT.
        heading = next((index for index in range(len(lines) - 3)
                        if (re.fullmatch(r'description', lines[index], re.I)
                            and re.fullmatch(r'qty|quantity', lines[index + 1], re.I)
                            and re.fullmatch(r'unit\s+price|rate\s*/\s*unit', lines[index + 2], re.I)
                            and re.fullmatch(r'amount', lines[index + 3], re.I))), None)
        if heading is not None:
            index = heading + 4
            inline = re.compile(rf'^(.+?)\s+(\d+(?:\.\d+)?)\s+{amount}\s*{amount}$', re.I)
            while index < len(lines):
                if re.match(r'^(?:subtotal|tax|vat|total|balance|payment\s+terms)\b', lines[index], re.I):
                    break
                match = inline.fullmatch(lines[index])
                if match:
                    add(*match.groups())
                    index += 1
                elif (index + 3 < len(lines) and number.fullmatch(lines[index + 1])
                      and money.fullmatch(lines[index + 2]) and money.fullmatch(lines[index + 3])):
                    add(lines[index], lines[index + 1], money.fullmatch(lines[index + 2]).group(1),
                        money.fullmatch(lines[index + 3]).group(1))
                    index += 4
                else:
                    index += 1
    return items


def _printed_service_date(lines: list[str], boundary: str) -> str | None:
    expanded = boundary.replace('start', 'start(?:ing)?').replace('end', 'end(?:ing)?')
    label = re.compile(rf"^(?:for\s+)?(?:service|billing)\s+(?:{expanded})(?:\s+date)?\b\s*:?")
    for index, line in enumerate(lines):
        match = label.search(line.casefold())
        if not match:
            continue
        candidates = [line[match.end():]]
        if index + 1 < len(lines) and not re.match(r"^(?:service|billing)\s+(?:start|end|from|to)\b",
                                                   lines[index + 1], re.I):
            candidates.append(lines[index + 1])
        for candidate in candidates:
            date_match = DATE_RE.search(candidate)
            if date_match:
                normalized = document_date(date_match.group(), '\n'.join(lines), settings.invoice_date_order)
                if normalized:
                    return normalized
                if normalize_date(date_match.group()):
                    return date_match.group()
    return None


def _account(lines: list[str]) -> str | None:
    candidates = _value_after_label(lines, r"\b(?:account\s*(?:number|no\.?|#)|billing\s+account)\s*[:#]?")
    for line in candidates:
        value = re.sub(r"^(?:Account\s*(?:Number|No\.?|#)|Billing\s+Account)\s*[:#]?\s*",
                       "", line, flags=re.IGNORECASE).strip()
        if re.fullmatch(r"(?:page|sheet)\s*\d+", value, re.IGNORECASE):
            continue
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 -]{4,38}", value) and re.search(r"\d", value):
            return value
    return None


def _contract_id(lines: list[str]) -> str | None:
    for line in _value_after_label(lines, r'\bcontract\s*(?:id|number|no\.?)\s*[:#]?'):
        identifier = line.strip().split()[0] if line.strip() else ''
        if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9/_-]{3,79}', identifier) and re.search(r'\d', identifier):
            return identifier
    return None


def _printed_billing_account(lines: list[str]) -> str | None:
    """Use only an explicit invoice Billing Account label as an MDM account clue.

    A bank Account Number is different and must not select an MDM account.
    """
    for line in _value_after_label(lines, r'^\s*billing\s+account\s*[:#]?'):
        identifier = line.strip()
        if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9/_ -]{3,79}', identifier) and re.search(r'\d', identifier):
            return identifier
    return None


def _currency(lines: list[str]) -> str | None:
    """Read an explicit currency label, including PDF text split into cells."""
    for index, line in enumerate(lines):
        labeled = re.search(r'\bcurrency\s*[:#-]?\s*([A-Z]{3})\b', line, re.I)
        if labeled:
            return labeled.group(1).upper()
        if re.fullmatch(r'currency\s*[:#-]?', line, re.I) and index + 1 < len(lines):
            next_line = lines[index + 1].strip()
            if re.fullmatch(r'[A-Z]{3}', next_line, re.I) and next_line.upper() not in {'TAX', 'NET', 'DUE', 'QTY'}:
                return next_line.upper()
    for line in lines:
        contextual = re.search(r'\b(?:amounts\s+in|(?:total|amount\s+due|balance\s+due)\s*\()\s*([A-Z]{3})\b', line, re.I)
        if contextual:
            return contextual.group(1).upper()
    return None


def _vendor_email(lines: list[str], vendor_name: str | None) -> str | None:
    """Choose a printed contact, preferring the vendor when several appear."""
    candidates: list[tuple[str, str]] = []
    for index, line in enumerate(lines):
        for match in EMAIL.finditer(line):
            email = match.group()
            domain = email.rsplit('@', 1)[1].casefold()
            # Synthetic training invoices use reserved test domains. OCR can
            # also turn `billing10@...` into `billing! 0@...`; neither is a
            # usable company contact for the cumulative report.
            if domain.endswith(('.test', '.example', '.invalid')):
                continue
            if not re.search(r'[A-Za-z]', email.split('@', 1)[0]):
                continue
            context = ' '.join(lines[max(0, index - 1):index + 1]).casefold()
            candidates.append((email, context))
    if not candidates:
        return None
    vendor_tokens = [token.casefold() for token in re.findall(r'[A-Za-z]{4,}', vendor_name or '')
                     if token.casefold() not in {'technologies', 'limited', 'company'}]
    def score(item: tuple[str, str]) -> int:
        email, context = item
        domain = email.split('@', 1)[1].casefold().replace('-', '').replace('.', '')
        points = 0
        if any(token in domain for token in vendor_tokens):
            points += 5
        if re.search(r'questions|contact|vendor\s+email|accounting|remit\s+to', context):
            points += 3
        if re.search(r'bill\s+to|accounts\s+payable|attn', context):
            points -= 4
        return points
    ranked = sorted(candidates, key=score, reverse=True)
    return ranked[0][0]


def _vendor_region(lines: list[str], vendor_name: str | None) -> str | None:
    """Use only the printed vendor-address block, never the Bill To address."""
    if not vendor_name:
        return None
    bill_to = next((i for i, line in enumerate(lines)
                    if re.search(r'\bbill\s+to\b', line, re.I)), len(lines))
    vendor_at = next((i for i, line in enumerate(lines[:bill_to])
                      if vendor_name.casefold() in line.casefold()), None)
    if vendor_at is None:
        return None

    def city(text: str) -> str:
        text = re.sub(r'^\d{4,6}\s+', '', text.strip())
        text = re.sub(r'\s+(?:\d{4,6}|[A-Z]{1,2}\d[A-Z\d]?\s+\d[A-Z]{2})$', '', text)
        return text.strip()

    for line in reversed(lines[vendor_at + 1:min(bill_to, vendor_at + 8)]):
        if re.search(r'\b(?:invoice|due|date|reference)\b', line, re.I):
            continue
        parts = [part.strip() for part in line.split(',') if part.strip()]
        if len(parts) < 2:
            continue
        last = parts[-1]
        state_postal = re.fullmatch(r'([A-Z]{2})\s+\d{4,6}', last)
        if state_postal and len(parts) >= 2:
            return f'{city(parts[-2])}, {state_postal.group(1)}'
        if last.casefold() in {'usa', 'united states', 'canada'} and len(parts) >= 3:
            area = re.match(r'([A-Z]{2})\b', parts[-2])
            if area:
                return f'{city(parts[-3])}, {area.group(1)}, {last}'
        if last.casefold() in {'singapore'} or re.fullmatch(r'Singapore\s+\d{6}', last, re.I):
            return 'Singapore'
        if re.fullmatch(r'[A-Za-z][A-Za-z ]+', last) and len(last) > 3:
            location = city(parts[-2])
            if location and re.search(r'[A-Za-z]', location):
                return f'{location}, {last}'
    return None


def extract_invoice(document_data: bytes, filename: str) -> dict[str, Any]:
    """Use OCR and the user's trained line models to draft invoice fields."""
    if not document_data:
        raise ValueError("Invoice document is empty")
    text = extract_document_text(filename, document_data)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
    invoice: dict[str, Any] = {}
    derived_fields: list[str] = []
    extraction_issues: list[str] = []
    printed_dates: dict[str, str] = {}

    def put(name: str, value: object) -> None:
        if value not in (None, ""):
            invoice[name] = value

    put("invoice_number", _invoice_number(lines))
    put("invoice_date", _date_from(lines, r"^(?:invoice\s+date|date\s+of\s+issue|date(?=\s*[:#]|\s*$|\s+\d))\s*[:#]?", "invoice_date"))
    put("vendor_name", _company_name(lines, "vendor_name"))
    put("customer_name", _company_name(lines, "customer_name"))
    put("vendor_email", _vendor_email(lines, invoice.get('vendor_name')))
    put("bank_account_number", _account(lines))
    put("contract_id", _contract_id(lines) or _printed_billing_account(lines))
    put("subtotal", _money_after_label(lines, r"^subtotal\b"))
    put("tax_amount", _money_after_label(
        lines, r"^(?:tax\s*/\s*vat|value\s+added\s+tax|tax\s+amount|sales\s+tax(?:\s+not\s+included)?|vat\s+amount|tax)\b"))
    put("total_amount", _money_after_label(lines, r"^(?:total\s+amount\s+due|amount\s+due|balance\s+due|grand\s+total|total\s+due|invoice\s+amount)\b")
        or _money_after_label(lines, r'^total\b')
        or _arithmetically_supported_total(lines))
    if ('subtotal' not in invoice and invoice.get('tax_amount') is not None
            and invoice.get('total_amount') is not None
            and not re.search(r'^\s*(?:discount|shipping)(?:\s*\(|\s*:|\s*$)', text, re.I | re.M)):
        net = Decimal(invoice['total_amount']) - Decimal(invoice['tax_amount'])
        if net >= 0:
            put('subtotal', format(net, '.2f'))
            derived_fields.append('subtotal')
    put("currency", _currency(lines))
    for line in _ranked_lines(lines, "contact_email") + lines:
        match = EMAIL.search(line)
        if match:
            put("customer_email", match.group())
            break
    period_start, period_end = _period(lines)
    start = _printed_service_date(lines, 'start|from') or period_start
    end = _printed_service_date(lines, 'end|to') or period_end
    layout = {}
    if filename.lower().endswith('.pdf') and document_data.startswith(b'%PDF'):
        from services.pdf_layout_fields import extract_layout_fields
        try:
            layout = extract_layout_fields(document_data)
        except (ValueError, RuntimeError):
            layout = {}
        if not layout and not start and not end:
            from services.ocr_service import extract_image_layout
            try:
                layout = extract_image_layout(filename, document_data)
            except (OSError, RuntimeError, ValueError):
                layout = {}
        start = layout.get('service_start_date', start)
        end = layout.get('service_end_date', end)
    elif filename.lower().endswith(('.jpg', '.jpeg', '.png', '.tif', '.tiff', '.bmp')):
        from services.ocr_service import extract_image_layout
        try:
            layout = extract_image_layout(filename, document_data)
        except (OSError, RuntimeError):
            extraction_issues.append('Additional table OCR was unavailable; verify service dates')
        start = layout.get('service_start_date', start)
        end = layout.get('service_end_date', end)
    if layout.get('_service_period_issue'):
        start = end = None
        extraction_issues.append(layout['_service_period_issue'])
    elif not layout.get('service_start_date') and len(_period_candidates(lines)) > 1:
        start = end = None
        extraction_issues.append('Multiple distinct billing/service periods; review each service line')
    for name in ('vendor_name', 'customer_name', 'vendor_address', 'customer_address',
                 'subtotal', 'tax_amount', 'total_amount'):
        if layout.get(name):
            invoice[name] = layout[name]
    if layout.get('subtotal') and 'subtotal' in derived_fields:
        derived_fields.remove('subtotal')
    elif 'subtotal' in derived_fields and layout.get('total_amount') and invoice.get('tax_amount') is not None:
        invoice['subtotal'] = format(Decimal(invoice['total_amount']) - Decimal(invoice['tax_amount']), '.2f')
    if ('subtotal' not in invoice and invoice.get('tax_amount') is not None
            and invoice.get('total_amount') is not None
            and not re.search(r'^\s*(?:discount|shipping)(?:\s*\(|\s*:|\s*$)', text, re.I | re.M)):
        net = Decimal(invoice['total_amount']) - Decimal(invoice['tax_amount'])
        if net >= 0:
            invoice['subtotal'] = format(net, '.2f')
            derived_fields.append('subtotal')
    put("service_start_date", start)
    put("service_end_date", end)
    if start and end:
        put("billing_period", f"{start} to {end}")
    put("due_date", _date_from(lines, r"\b(?:due\s+date|payment\s+due)\s*[:#]?"))
    if "due upon receipt" in text.casefold() or "payment due upon receipt" in text.casefold():
        put("payment_terms", "Due Upon Receipt")
    if "market data" in text.casefold():
        put("scope", "Market Data")
    region_lines = ([invoice['vendor_name']] + invoice['vendor_address'].splitlines() + ['Bill To:']
                    if invoice.get('vendor_name') and invoice.get('vendor_address') else lines)
    put("region", _vendor_region(region_lines, invoice.get('vendor_name')))

    # Normalize extracted dates together, using explicit document-wide evidence.
    # Avoid normalizing a raw ambiguous date earlier and losing its source order.
    for name in ('invoice_date', 'due_date'):
        if invoice.get(name):
            printed_dates[name] = invoice[name]
            normalized = document_date(invoice[name], text, settings.invoice_date_order)
            if normalized:
                invoice[name] = normalized
            elif normalize_date(invoice[name]) is None:
                invoice.pop(name)
                extraction_issues.append(f'{name}: printed date is invalid')
    for name in ('service_start_date', 'service_end_date'):
        if invoice.get(name):
            printed_dates[name] = next((match.group() for match in DATE_RE.finditer(text)
                if document_date(match.group(), text, settings.invoice_date_order) == invoice[name]), invoice[name])

    return {"invoice": invoice, "line_items": _service_lines(lines), "field_confidence": {},
            "_extraction_issues": extraction_issues,
            "_printed_dates": printed_dates,
            "_local_draft": bool(invoice), "_ocr_only": not bool(invoice),
            "_ocr_character_count": len(text), "_derived_fields": derived_fields}
