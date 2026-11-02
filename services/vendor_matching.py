"""Conservative vendor/account matching against a local MDM export.

The lookup never invents an account: uncertain or conflicting candidates stay
unmatched for a person to resolve.  Contiguous and ordered-token comparisons
cover word sequences of any length without enumerating 2**N combinations.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from datetime import date, datetime
from zoneinfo import ZoneInfo
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from zipfile import BadZipFile

from utils.date_utils import normalize_date, document_date
from config.settings import settings


LEGAL_SUFFIXES = {
    'llc', 'ltd', 'limited', 'inc', 'incorporated', 'corp', 'corporation',
    'co', 'company', 'plc', 'pvt', 'private', 'gmbh', 'ag', 'sa',
}
GENERIC_WORDS = {'the', 'and', 'of', 'for', 'services', 'service', 'group'}
REGION_GROUPS = {
    'apac': 'apac', 'asia pacific': 'apac', 'asia': 'apac',
    'hong kong': 'apac', 'singapore': 'apac', 'india': 'apac',
    'china': 'apac', 'japan': 'apac', 'australia': 'apac',
    'emea': 'emea', 'europe middle east africa': 'emea', 'europe': 'emea',
    'united kingdom': 'emea', 'uk': 'emea', 'germany': 'emea',
    'france': 'emea', 'uae': 'emea',
    'americas': 'americas', 'north america': 'north america',
    'united states': 'north america', 'usa': 'north america', 'us': 'north america',
    'canada': 'north america', 'latam': 'latam', 'latin america': 'latam',
    'brazil': 'latam', 'mexico': 'latam', 'argentina': 'latam',
    'africa': 'africa', 'south africa': 'africa',
}
US_STATES = {
    'al', 'ak', 'az', 'ar', 'ca', 'co', 'ct', 'de', 'fl', 'ga', 'hi', 'id',
    'il', 'in', 'ia', 'ks', 'ky', 'la', 'me', 'md', 'ma', 'mi', 'mn', 'ms',
    'mo', 'mt', 'ne', 'nv', 'nh', 'nj', 'nm', 'ny', 'nc', 'nd', 'oh', 'ok',
    'or', 'pa', 'ri', 'sc', 'sd', 'tn', 'tx', 'ut', 'vt', 'va', 'wa', 'wv',
    'wi', 'wy', 'dc',
}


def _words(value: str) -> tuple[str, ...]:
    folded = unicodedata.normalize('NFKD', value).casefold()
    folded = ''.join(char for char in folded if not unicodedata.combining(char))
    return tuple(re.findall(r'[a-z0-9]+', folded))


def _business_words(value: str) -> tuple[str, ...]:
    words = list(_words(value))
    while len(words) > 1 and words[-1] in LEGAL_SUFFIXES:
        words.pop()
    return tuple(words)


def _longest_contiguous(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    previous = [0] * (len(right) + 1)
    longest = 0
    for word in left:
        current = [0] * (len(right) + 1)
        for index, other in enumerate(right, 1):
            if word == other:
                current[index] = previous[index - 1] + 1
                longest = max(longest, current[index])
        previous = current
    return longest


def _ordered_overlap(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    previous = [0] * (len(right) + 1)
    for word in left:
        current = [0] * (len(right) + 1)
        for index, other in enumerate(right, 1):
            current[index] = (previous[index - 1] + 1 if word == other else
                              max(previous[index], current[index - 1]))
        previous = current
    return previous[-1]


def _within_one_edit(left: str, right: str) -> bool:
    """One OCR substitution/insertion/deletion, without broad fuzzy guessing."""
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) <= 1
    shorter, longer = sorted((left, right), key=len)
    index = 0
    while index < len(shorter) and shorter[index] == longer[index]:
        index += 1
    return shorter[index:] == longer[index + 1:]


def vendor_similarity(invoice_vendor: str, account_vendor: str) -> float:
    """Score supplied names using vendor-independent rules and word evidence."""
    original, candidate_original = _words(invoice_vendor), _words(account_vendor)
    left, right = _business_words(invoice_vendor), _business_words(account_vendor)
    if not left or not right:
        return 0.0
    if original == candidate_original:
        return 100.0
    if left == right:
        return 99.0
    meaningful_left = {word for word in left if word not in GENERIC_WORDS}
    meaningful_right = {word for word in right if word not in GENERIC_WORDS}
    shared = meaningful_left & meaningful_right
    # Some masters retain the trailing organization qualifier "International"
    # while the invoice prints a legal suffix such as Ltd. Treat this as strong
    # evidence only when at least two leading business words match exactly.
    shorter, longer = sorted((left, right), key=len)
    shorter_meaningful = {word for word in shorter if word not in GENERIC_WORDS}
    if (len(shorter_meaningful) >= 2 and len(longer) == len(shorter) + 1
            and longer[:-1] == shorter and longer[-1] == 'international'):
        return 96.0
    # A full business name with one OCR character error is stronger evidence
    # than an abbreviated name, but never outranks normalized exact matches.
    if (len(left) == len(right) and len(meaningful_left) >= 2
            and len(meaningful_right) >= 2 and shared
            and _within_one_edit(' '.join(left), ' '.join(right))):
        return 97.0

    # MDM can contain only the distinctive leading brand words, without an
    # explicit alias. Require
    # at least two non-generic words and the complete shorter name in order.
    # A single OCR character error in that prefix is allowed, not arbitrary
    # token substitutions, reordering, or matching on one common word.
    prefix_score = 0.0
    if len(shorter) < len(longer) and len(shorter_meaningful) >= 2:
        prefix = longer[:len(shorter)]
        if prefix == shorter:
            prefix_score = 88.0
        elif shared and _within_one_edit(' '.join(prefix), ' '.join(shorter)):
            prefix_score = 82.0
    if len(shared) < 2 and not (len(left) == len(right) == 1 and shared):
        return prefix_score
    longest = _longest_contiguous(left, right)
    ordered = _ordered_overlap(left, right)
    longer = max(len(left), len(right))
    shorter = min(len(left), len(right))
    token_coverage = len(shared) / max(len(meaningful_left | meaningful_right), 1)
    score = 100 * (
        .30 * SequenceMatcher(None, ' '.join(left), ' '.join(right)).ratio()
        + .30 * longest / longer
        + .20 * token_coverage
        + .15 * ordered / longer
        + .05 * min(longest / shorter, 1)
    )
    return max(round(score, 2), prefix_score)


def _region_key(value: str) -> str:
    normalized = ' '.join(_words(value))
    if normalized in REGION_GROUPS:
        return REGION_GROUPS[normalized]
    words = _words(value)
    if words and words[-1] in US_STATES:
        return 'north america'
    for phrase, group in REGION_GROUPS.items():
        if len(phrase) > 2 and re.search(rf'\b{re.escape(phrase)}\b', normalized):
            return group
    return normalized


def _region_rank(invoice_region: str, restriction: str) -> int:
    """Prefer exact/detailed regions; use groups only for broad restrictions."""
    if not restriction:
        return 1
    if not invoice_region:
        return 0
    invoice_normalized = ' '.join(_words(invoice_region))
    restriction_normalized = ' '.join(_words(restriction))
    if invoice_normalized == restriction_normalized:
        return 4
    if (len(restriction_normalized) > 2 and restriction_normalized in invoice_normalized
            or len(invoice_normalized) > 2 and invoice_normalized in restriction_normalized):
        return 3
    invoice_group = _region_key(invoice_region)
    restriction_group = _region_key(restriction)
    if restriction_normalized in REGION_GROUPS and invoice_group == restriction_group:
        return 2
    if {invoice_group, restriction_group} <= {'americas', 'north america', 'latam'} and (
        invoice_group == 'americas' or restriction_group == 'americas'
    ):
        return 2
    return -1


@dataclass(frozen=True)
class VendorAccount:
    account: str
    vendor: str
    restricted_to: str
    aliases: tuple[str, ...] = ()
    contract_status: str = 'NOT_CHECKED'
    contract_reason: str = ''
    contract_start_date: str = ''
    contract_end_date: str = ''


@dataclass(frozen=True)
class VendorMatch:
    account: VendorAccount
    vendor_score: float


@dataclass(frozen=True)
class VendorResolution:
    match: VendorMatch | None
    status: str
    reason: str = ''


_VENDOR_EXPORT_DATE = re.compile(
    r'vendoracc(?:ounts?)?.*?(?P<date>\d{8})(?!\d)', re.IGNORECASE)
_CONTRACT_EXPORT_DATE = re.compile(r'contracts?.*?(?P<date>\d{8})(?!\d)', re.IGNORECASE)


def catalog_paths(folder: Path, today: date | None = None, *, allow_legacy: bool = True) -> tuple[Path, Path]:
    """Choose today's Vendor Accounts and Contracts exports.

    Operational Vendor Accounts exports include ``VendorAcc`` followed later
    by a YYYYMMDD stamp, for example
    ``47724_VendorAcc_20261007T10_59_26.csv``. The rest of
    the filename is not prescribed. Contracts use the equivalent
    ``anything_contract_anything_YYYYMMDD_anything.csv`` convention. Old exports are
    deliberately ignored. The legacy ``vendor_accounts.csv/.xlsx`` name
    remains supported when no dated exports are present. Contracts follow the
    same date rule when their filename contains ``contracts``; legacy
    ``contracts.csv/.xlsx`` remains supported.
    """
    today = today or datetime.now(ZoneInfo('Asia/Kolkata')).date()
    files = ([item for item in folder.iterdir()
              if item.is_file() and item.suffix.casefold() in {'.csv', '.xlsx'}]
             if folder.is_dir() else [])

    dated_vendor_files = []
    current_vendor_files = []
    for item in files:
        match = _VENDOR_EXPORT_DATE.search(item.stem)
        if not match:
            continue
        dated_vendor_files.append(item)
        if match.group('date') == today.strftime('%Y%m%d'):
            current_vendor_files.append(item)

    static_vendor_files = [item for item in files
                           if item.stem.casefold() == 'vendor_accounts']
    if dated_vendor_files:
        vendor_files = current_vendor_files
        if not vendor_files:
            expected = today.strftime('%Y%m%d')
            raise ValueError(f'MDM folder has no Vendor Accounts export dated today ({expected}).')
    else:
        vendor_files = static_vendor_files if allow_legacy else []
        if not allow_legacy:
            raise ValueError(f'MDM folder has no Vendor Accounts export dated today ({today:%Y%m%d}).')
    if len(vendor_files) > 1:
        if dated_vendor_files:
            raise ValueError('MDM folder contains multiple current Vendor Accounts masters; keep one CSV or XLSX.')
        raise ValueError('MDM folder contains multiple vendor_accounts masters; keep one CSV or XLSX.')

    dated_contract_files = []
    current_contract_files = []
    for item in files:
        match = _CONTRACT_EXPORT_DATE.search(item.stem)
        if not match:
            continue
        dated_contract_files.append(item)
        if match.group('date') == today.strftime('%Y%m%d'):
            current_contract_files.append(item)

    static_contract_files = [item for item in files if item.stem.casefold() == 'contracts']
    if dated_contract_files:
        contract_files = current_contract_files
        if not contract_files:
            expected = today.strftime('%Y%m%d')
            raise ValueError(f'MDM folder has no Contracts export dated today ({expected}).')
    else:
        contract_files = static_contract_files if allow_legacy else []
        if not allow_legacy:
            raise ValueError(f'MDM folder has no Contracts export dated today ({today:%Y%m%d}).')
    if len(contract_files) > 1:
        if dated_contract_files:
            raise ValueError('MDM folder contains multiple current Contracts masters; keep one CSV or XLSX.')
        raise ValueError('MDM folder contains multiple contracts masters; keep one CSV or XLSX.')

    vendor = vendor_files[0] if vendor_files else folder / 'vendor_accounts.csv'
    contracts = contract_files[0] if contract_files else folder / 'contracts.csv'
    return vendor, contracts


def _master_headers(values) -> list[str]:
    aliases = {'accountnumber': 'Account Number', 'accountno': 'Account Number',
               'account': 'Account', 'vendor': 'Vendor', 'vendorname': 'Vendor',
               'restrictedto': 'Restricted To', 'contractid': 'Contract ID',
               'contractnumber': 'Contract ID', 'startdate': 'Start Date',
               'contractstartdate': 'Start Date', 'enddate': 'End Date',
               'contractenddate': 'End Date', 'vendoralias': 'Vendor Alias'}
    headers = [aliases.get(re.sub(r'[^a-z0-9]', '', str(value or '').casefold()),
                           str(value or '').strip()) for value in values]
    populated = [header for header in headers if header]
    if len(set(populated)) != len(populated):
        raise ValueError('Master has duplicate or conflicting column headers')
    return headers


def read_master_rows(path: Path, required: set[str]) -> list[dict[str, str]]:
    """Read the first worksheet or CSV without ever writing to a master."""
    if path.suffix.casefold() == '.xlsx':
        try:
            book = load_workbook(path, read_only=True, data_only=True)
        except (BadZipFile, InvalidFileException, KeyError) as exc:
            raise ValueError(f'{path.name} is not a readable XLSX workbook.') from exc
        try:
            rows = book.worksheets[0].iter_rows(values_only=True)
            headers = _master_headers(next(rows, ()))
            if not required.issubset(headers):
                raise ValueError(f'{path.name} requires {", ".join(sorted(required))} columns')
            def text(cell):
                return cell.isoformat()[:10] if isinstance(cell, (datetime, date)) else str(cell) if cell is not None else ''
            return [dict(zip(headers, map(text, row))) for row in rows]
        finally:
            book.close()
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames:
            reader.fieldnames = _master_headers(reader.fieldnames)
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f'{path.name} requires {", ".join(sorted(required))} columns')
        return list(reader)


def load_vendor_accounts(path: Path, contracts_path: Path | None = None) -> list[VendorAccount]:
    """Read accounts, then check matching Contract IDs for dated records.

    Contracts are evidence only; they never replace the account or vendor
    selected from Vendor Accounts.
    """
    if not path.is_file():
        return []
    try:
        vendor_rows = read_master_rows(path, {'Account Number', 'Vendor', 'Restricted To'})
        account_column = 'Account Number'
    except ValueError:
        try:
            vendor_rows = read_master_rows(path, {'Account', 'Vendor', 'Restricted To'})
            account_column = 'Account'
        except ValueError as exc:
            raise ValueError(
                f'{path.name} requires Account Number (or Account), Vendor, and Restricted To columns') from exc
    records = [row for row in vendor_rows if row.get(account_column) and row.get('Vendor')]
    contracts: dict[str, list[tuple[str, str]]] = {}
    master_issue = ''
    if contracts_path is not None:
        if contracts_path.is_file():
            try:
                contract_rows = read_master_rows(contracts_path, {'Contract ID', 'Start Date', 'End Date'})
            except ValueError:
                master_issue = 'Contracts file needs Contract ID, Start Date, and End Date columns'
            else:
                for row in contract_rows:
                    contract_id = (row.get('Contract ID') or '').strip().casefold()
                    if contract_id:
                        contracts.setdefault(contract_id, []).append(
                            ((row.get('Start Date') or '').strip(), (row.get('End Date') or '').strip()))

    def evidence(account: str) -> tuple[str, str, str, str]:
        if contracts_path is None:
            return 'NOT_CHECKED', '', '', ''
        if not contracts_path.is_file():
            return 'NOT_CHECKED', 'Contracts file is unavailable; date check was not run', '', ''
        if master_issue:
            return 'INVALID_MASTER', master_issue, '', ''
        found = contracts.get(account.casefold(), [])
        if not found:
            return 'NOT_FOUND', f'No Contract ID matches Billing Account {account}', '', ''
        if len(found) != 1:
            return 'AMBIGUOUS', f'Multiple contracts match Billing Account {account}', '', ''
        start, end = found[0]
        if not start or not end:
            return 'MISSING_DATES', f'Contract {account} lacks Start Date or End Date', start, end
        start_iso = document_date(start, start + ' ' + end, settings.invoice_date_order)
        end_iso = document_date(end, start + ' ' + end, settings.invoice_date_order)
        if not start_iso or not end_iso or start_iso > end_iso:
            return 'INVALID_DATES', f'Contract {account} has invalid Start Date or End Date', start, end
        today = datetime.now(ZoneInfo('Asia/Kolkata')).date()
        if date.fromisoformat(end_iso) < today:
            return 'EXPIRED', f'Contract {account} expired on {end_iso}', start_iso, end_iso
        if date.fromisoformat(start_iso) > today:
            return 'NOT_STARTED', f'Contract {account} starts on {start_iso}', start_iso, end_iso
        return 'PRESENT', '', start_iso, end_iso

    entries = []
    for row in records:
        account = (row[account_column] or '').strip()
        entries.append(VendorAccount(account, (row['Vendor'] or '').strip(),
                                     (row['Restricted To'] or '').strip(),
                                     tuple(alias.strip() for alias in (row.get('Vendor Alias') or '').split(';')
                                           if alias.strip()), *evidence(account)))
    return entries


def resolve_vendor_account(vendor: str | None, region: str | None,
                           accounts: list[VendorAccount], minimum_score: float = 70.0,
                           contract_id: str | None = None) -> VendorResolution:
    """Match the vendor first; use region only to resolve multiple accounts.

    A printed contract/account ID is not allowed to bypass an ambiguous vendor
    and region match. The invoice number is never an account identifier.
    """
    if not vendor:
        return VendorResolution(None, 'NOT_FOUND', 'Invoice vendor is blank')
    if not accounts:
        return VendorResolution(None, 'NOT_FOUND', 'MDM vendor master is empty or unavailable')
    ranked = [(max(vendor_similarity(vendor, name)
                   for name in (account.vendor, *account.aliases)), account)
              for account in accounts]
    ranked = [(score, account) for score, account in ranked if score >= minimum_score]
    if not ranked:
        return VendorResolution(None, 'NOT_FOUND', 'No sufficiently similar MDM vendor')

    best_score = max(score for score, _ in ranked)
    # Exact normalized names take precedence over suffix-only matches; fuzzy
    # names within three points of the best fuzzy score remain candidates.
    if best_score >= 99:
        candidates = [(score, account) for score, account in ranked if score == best_score]
    else:
        candidates = [(score, account) for score, account in ranked if best_score - score < 3]
    # A single matching master row is sufficient. Multiple rows must always be
    # resolved through Bill To Region versus Restricted To, even when duplicate
    # rows happen to carry the same account number.
    if len(candidates) == 1:
        score, account = candidates[0]
        return VendorResolution(VendorMatch(account, score), 'MATCHED')

    if not _region_key(region or ''):
        return VendorResolution(None, 'LOW_CONFIDENCE',
                                'Multiple VendorAcc records match the vendor; no Bill To Region is available')
    regional = [(rank, score, account) for score, account in candidates
                if account.restricted_to
                and (rank := _region_rank(region or '', account.restricted_to)) > 0]
    if not regional:
        restrictions = ', '.join(sorted({account.restricted_to or '(blank)'
                                         for _, account in candidates}))
        return VendorResolution(None, 'LOW_CONFIDENCE',
                                f"Multiple MDM accounts match the vendor, but invoice Region '{region}' "
                                f'does not match Restricted To: {restrictions}')
    highest_rank = max(rank for rank, _, _ in regional)
    regional = [(score, account) for rank, score, account in regional if rank == highest_rank]
    if len({account.account for _, account in regional}) > 1:
        identifiers = ', '.join(sorted({account.account for _, account in regional}))
        return VendorResolution(None, 'LOW_CONFIDENCE',
                                'Multiple MDM accounts have the same vendor and region: ' + identifiers)
    score, account = regional[0]
    return VendorResolution(VendorMatch(account, score), 'MATCHED')


def match_vendor_account(vendor: str | None, region: str | None,
                         accounts: list[VendorAccount], minimum_score: float = 70.0,
                         contract_id: str | None = None) -> VendorMatch | None:
    """Compatibility wrapper returning only unambiguous matches."""
    return resolve_vendor_account(vendor, region, accounts, minimum_score,
                                  contract_id).match
