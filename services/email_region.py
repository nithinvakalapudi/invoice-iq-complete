"""Read only an explicitly labelled region from an email's text or subject."""
from __future__ import annotations

import re

from services.vendor_matching import _region_key


REGION_LINE = re.compile(
    r'(?im)^\s*(?:vendor\s+)?region\s*[:\-]\s*([^\r\n;<>]{2,80})\s*$'
)
SUBJECT_REGION = re.compile(r'(?i)\b(?:vendor\s+)?region\s*[:\-]\s*([A-Za-z][A-Za-z ,]{1,50})')


def email_region(subject: str | None, body: str | None) -> tuple[str, str]:
    """Return (region, issue); conflicting labelled mentions must not pick one."""
    mentions = [match.group(1).strip(' .') for match in REGION_LINE.finditer((body or '')[:32000])]
    mentions.extend(match.group(1).strip(' .') for match in SUBJECT_REGION.finditer((subject or '')[:500]))
    keys = {_region_key(value) for value in mentions if value}
    if len(keys) > 1:
        return '', 'Conflicting regions in the email; Billing Account needs manual review'
    return (mentions[0] if mentions else ''), ''
