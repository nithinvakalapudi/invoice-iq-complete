"""Read printed field evidence using native PDF word coordinates."""
from __future__ import annotations

import re
from datetime import datetime

import pymupdf

from utils.date_utils import document_date, normalize_date
from config.settings import settings

_DATE = re.compile(r'^(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})$')


def extract_layout_fields(data: bytes) -> dict[str, str]:
    """Select dates beneath service/billing headers, never contract headers.

    All values must be printed. Conflicting periods remain unresolved rather
    than being collapsed to an invented invoice-wide range.
    """
    with pymupdf.open(stream=data, filetype='pdf') as document:
        pages = [(page.rect.width, page.rect.height, page.get_text('words', sort=True))
                 for page in document]
    return extract_word_fields(pages)


def extract_word_fields(pages) -> dict[str, str]:
    """Shared geometry logic for PDF text and OCR word bounding boxes."""
    fields: dict[str, str] = {}
    periods: set[tuple[str, str]] = set()
    service_columns = False
    for width, height, words in pages:
            from services.layout_values import scalar_layout_fields
            fields.update(scalar_layout_fields(words, width))
            context = ' '.join(w[4] for w in words)
            dates = [w for w in words if _DATE.fullmatch(w[4])]

            def date_value(value):
                return (document_date(value, context, settings.invoice_date_order)
                        or (value if normalize_date(value) else None))

            def ordered(start, end):
                a = document_date(start, context, settings.invoice_date_order)
                b = document_date(end, context, settings.invoice_date_order)
                return not (a and b) or a <= b

            def header_text(anchor):
                # Wrapped headings share a column, even when text order does not.
                height = max(anchor[3] - anchor[1], 6)
                return ' '.join(w[4] for w in words
                                if abs(w[0] - anchor[0]) < 30
                                and anchor[1] - height <= w[1] <= anchor[3] + height * 2).casefold()

            def column_dates(anchor, neighbors):
                center = (anchor[0] + anchor[2]) / 2
                other_centers = sorted((w[0] + w[2]) / 2 for w in neighbors
                                       if abs(w[1] - anchor[1]) < 20
                                       and abs(w[0] - anchor[0]) >= 30)
                left = max((x for x in other_centers if x < center - 8), default=0)
                right = min((x for x in other_centers if x > center + 8), default=width)
                # Use a narrow column; do not consume adjacent account/contract dates.
                low, high = (left + center) / 2, (center + right) / 2
                return [w for w in dates if low <= (w[0] + w[2]) / 2 <= high
                        and w[1] > anchor[3] and w[1] < anchor[3] + height * .45]

            anchors = [w for w in words if w[4].casefold().strip(':') in
                       {'billing', 'service', 'starting', 'ending', 'date(s)', 'contract',
                        'quantity', 'qty', 'net', 'vat', 'total', 'description', 'amount'}]
            start_columns, end_columns = [], []
            for anchor in anchors:
                heading = header_text(anchor)
                token = anchor[4].casefold().strip(':')
                if token == 'billing' and 'period' in heading:
                    service_columns = True
                    values = column_dates(anchor, anchors)
                    # Two dates in each billing-period cell; require agreement across rows.
                    for index in range(0, len(values) - 1, 2):
                        start, end = map(date_value, (values[index][4], values[index + 1][4]))
                        if start and end and ordered(start, end):
                            periods.add((start, end))
                if token in {'starting', 'ending'} and 'service' in heading:
                    service_columns = True
                    values = column_dates(anchor, anchors)
                    normalized = {date_value(w[4]) for w in values} - {None}
                    if token == 'starting':
                        start_columns.extend(normalized)
                    else:
                        end_columns.extend(normalized)
            if len(set(start_columns)) == len(set(end_columns)) == 1:
                start, end = start_columns[0], end_columns[0]
                if ordered(start, end):
                    periods.add((start, end))
    if len(periods) == 1:
        fields['service_start_date'], fields['service_end_date'] = next(iter(periods))
    elif service_columns:
        fields['_service_period_issue'] = ('Multiple distinct billing/service periods; review each service line'
                                           if len(periods) > 1 else
                                           'Service-date columns were found but their dates are unreadable or ambiguous')
    return fields
