"""Conservative date validation and ISO normalization."""
from __future__ import annotations

from datetime import datetime
import re

DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%m-%d-%Y", "%d.%m.%Y", "%Y/%m/%d",
                '%B %d, %Y', '%b %d, %Y', '%B %d %Y', '%b %d %Y', '%d %B %Y', '%d %b %Y')


def normalize_date(value: str | None) -> str | None:
    """Return ISO date only when an explicit supported date format parses."""
    if not value or not isinstance(value, str):
        return None
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), date_format).date().isoformat()
        except ValueError:
            continue
    return None


def document_date(value: str, context: str, order: str = 'AUTO') -> str | None:
    """Resolve numeric dates from document evidence; leave ambiguity unresolved."""
    if re.fullmatch(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}', value):
        return normalize_date(value)
    match = re.fullmatch(r'(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})', value)
    if not match:
        for fmt in ('%B %d, %Y', '%b %d, %Y', '%B %d %Y', '%b %d %Y', '%d %B %Y', '%d %b %Y'):
            try:
                return datetime.strptime(value.strip(), fmt).date().isoformat()
            except ValueError:
                continue
        return None
    evidence = set()
    for a, b, _ in re.findall(r'(?<!\d)(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})(?!\d)', context):
        if int(a) > 12 and int(b) <= 12:
            evidence.add('DMY')
        elif int(b) > 12 and int(a) <= 12:
            evidence.add('MDY')
    a, b, year = map(int, match.groups())
    if order == 'AUTO':
        if len(evidence) > 1:
            return None
        order = next(iter(evidence), '')
        if not order and a != b:
            return None
        order = order or 'DMY'
    if order not in {'DMY', 'MDY'}:
        return None
    try:
        return datetime(year + 2000 if year < 100 else year,
                        b if order == 'DMY' else a,
                        a if order == 'DMY' else b).date().isoformat()
    except ValueError:
        return None
