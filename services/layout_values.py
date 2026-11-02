"""Spatially associate explicit party labels and amount columns with values."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

MONEY_TOKEN = re.compile(r'(?<!\w)(?:\d{1,3}(?:[ ,.\u00a0]\d{3})+|\d+)[.,]\d{2}(?!\d)')


def money_values(text):
    values = []
    for match in MONEY_TOKEN.finditer(text):
        raw = match.group().replace(' ', '').replace('\u00a0', '')
        decimal_at = max(raw.rfind('.'), raw.rfind(','))
        normalized = re.sub(r'[.,]', '', raw[:decimal_at]) + '.' + raw[decimal_at + 1:]
        try:
            values.append(format(Decimal(normalized), '.2f'))
        except InvalidOperation:
            continue
    return values


def scalar_layout_fields(words, width):
    result = {}
    if not words:
        return result

    def row(anchor, right_only=False):
        center = (anchor[1] + anchor[3]) / 2
        tolerance = max((anchor[3] - anchor[1]) * .55, 2)
        return sorted([word for word in words
                       if abs((word[1] + word[3]) / 2 - center) <= tolerance
                       and (not right_only or word[0] >= anchor[2] - 1)], key=lambda word: word[0])

    party_headers = [word for word in words
                     if word[4].casefold().strip(':') in {'seller', 'supplier', 'vendor', 'client', 'customer'}
                     and (word[4].endswith(':') or len(row(word)) == 1)]
    for anchor in party_headers:
        token = anchor[4].casefold().strip(':')
        field = 'vendor_name' if token in {'seller', 'supplier', 'vendor'} else 'customer_name'
        neighbors = [word for word in party_headers if abs(word[1] - anchor[1]) < 12
                     and word[0] > anchor[2]]
        right = min((word[0] for word in neighbors), default=width)
        inline = ' '.join(word[4] for word in row(anchor, True) if word[0] < right - 8).strip()
        if inline and not re.search(r'\d|\b(?:address|tax|invoice|street)\b', inline, re.I):
            result[field] = inline
            continue
        candidates = [word for word in words if word[1] > anchor[3] - 1
                      and word[1] < anchor[3] + 45 and anchor[0] - 4 <= word[0] < right - 8]
        if candidates:
            first = min(candidates, key=lambda word: word[1])
            name = ' '.join(word[4] for word in row(first)
                            if anchor[0] - 4 <= word[0] < right - 8).strip()
            if name and not re.search(r'\d|\b(?:address|tax|invoice|street|bill|ship)\b', name, re.I):
                result[field] = name
        if field in result:
            address_words = [word for word in words if anchor[3] + 5 < word[1] < anchor[3] + 110
                             and anchor[0] - 4 <= word[0] < right - 8]
            lines = []
            for word in sorted(address_words, key=lambda item: (item[1], item[0])):
                if any(abs(word[1] - existing[0]) < 5 for existing in lines):
                    continue
                text = ' '.join(item[4] for item in row(word)
                                if anchor[0] - 4 <= item[0] < right - 8)
                if re.search(r'\b(?:tax|iban|account|invoice|items|description)\b', text, re.I):
                    break
                if text != result[field]:
                    lines.append((word[1], text))
            if lines:
                result[field.replace('_name', '_address')] = '\n'.join(line for _, line in lines)

    totals = []
    for anchor in words:
        if anchor[4].casefold().strip(':') not in {'total', 'due', 'balance'}:
            continue
        row_words = row(anchor)
        text = ' '.join(word[4] for word in row_words)
        if re.search(r'amount\s+due|balance\s+due|grand\s+total|total\s+amount\s+due', text, re.I):
            amounts = money_values(' '.join(word[4] for word in row(anchor, True)))
            if len(amounts) == 1:
                totals.append((anchor[1], {'total_amount': amounts[0]}))
        elif anchor[4].casefold().strip(':') == 'total':
            amounts = money_values(' '.join(word[4] for word in row(anchor, True)))
            if len(amounts) == 1:
                totals.append((anchor[1], {'total_amount': amounts[0]}))
            elif len(amounts) == 3:
                # Three amounts require a nearby Net/VAT/Gross summary heading
                # and independently checked arithmetic, not positional guessing.
                above = ' '.join(word[4] for word in words
                                 if anchor[1] - 85 < word[1] < anchor[1]).casefold()
                net, tax, total = map(Decimal, amounts)
                if all(label in above for label in ('net', 'vat', 'gross')) and abs(net + tax - total) <= Decimal('.02'):
                    totals.append((anchor[1], dict(zip(('subtotal', 'tax_amount', 'total_amount'), amounts))))
    if totals:
        result.update(max(totals, key=lambda item: item[0])[1])
    for anchor in words:
        if anchor[4].casefold().strip(':') not in {'tax', 'vat'}:
            continue
        same_row = row(anchor)
        heading = ' '.join(word[4] for word in same_row).casefold()
        if re.search(r'\brate\b|\[%\]', heading):
            continue
        right_words = [word for word in row(anchor, True) if '%' not in word[4]]
        candidates = [(word, money_values(word[4])) for word in right_words]
        candidates = [(word, values[0]) for word, values in candidates if len(values) == 1]
        if not candidates:
            continue
        total_headers = [word for word in words if word[4].casefold().strip(':') in {'total', 'amount'}
                         and anchor[1] - 160 < word[1] < anchor[1]
                         and word[0] > anchor[2]]
        if total_headers:
            last_column = max(word[0] for word in total_headers)
            candidates = [(word, value) for word, value in candidates if word[0] >= last_column - 20]
        elif len(candidates) != 1:
            continue
        if candidates:
            result.setdefault('tax_amount', max(candidates, key=lambda item: item[0][0])[1])
    return result
