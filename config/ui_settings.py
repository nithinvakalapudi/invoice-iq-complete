"""Persistent user-editable locations; never move the history DB or trained models."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from uuid import uuid4

from services.local_storage import LocalStorage, _atomic_write
from services.vendor_matching import catalog_paths, load_vendor_accounts


@dataclass(frozen=True)
class UiSettings:
    invoice_input_folder: str = ''
    output_folder: str = ''
    master_excel_filename: str = 'Invoice_History.xlsx'
    mdm_folder: str = ''
    review_threshold: float = 95
    rounding_tolerance: float = .02
    revision: str = ''


def settings_file(root: Path | str) -> Path:
    return Path(root).resolve() / 'ui_settings.json'


def load_ui_settings(base) -> UiSettings:
    defaults = UiSettings(output_folder=str(Path(base.local_storage_dir).resolve()),
                          review_threshold=base.minimum_field_confidence,
                          rounding_tolerance=base.default_tolerance)
    path = settings_file(base.local_storage_dir)
    if not path.is_file():
        return defaults
    raw = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(raw, dict) or set(raw) - set(asdict(defaults)):
        raise ValueError('Saved application settings are invalid; restore ui_settings.json.')
    return replace(defaults, **raw)


def _folder(value: str, label: str, required: bool = False, existing: bool = False) -> str:
    value = value.strip().strip('"')
    if not value:
        if required:
            raise ValueError(f'{label} is required.')
        return ''
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f'{label}: paste an absolute folder path on this computer.')
    path = path.resolve()
    if path.exists() and not path.is_dir():
        raise ValueError(f'{label} must be a folder, not a file.')
    if existing and not path.is_dir():
        raise ValueError(f'{label} does not exist.')
    return str(path)


def validate_ui_settings(value: UiSettings) -> UiSettings:
    input_folder = _folder(value.invoice_input_folder, 'Invoice input folder', existing=True)
    output_folder = _folder(value.output_folder, 'Output folder', required=True)
    mdm_folder = _folder(value.mdm_folder, 'MDM folder', existing=True)
    filename = value.master_excel_filename.strip()
    if (not filename or len(filename) > 140 or re.search(r'[<>:"/\\|?*\x00-\x1f]', filename)
            or not filename.lower().endswith('.xlsx') or filename != filename.strip(' .')
            or filename.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL',
                                                *(f'COM{i}' for i in range(1, 10)),
                                                *(f'LPT{i}' for i in range(1, 10))}):
        raise ValueError('Master Excel filename must be a simple .xlsx filename, without a folder path.')
    if filename.casefold() in {'vendor_accounts.xlsx', 'contracts.xlsx'}:
        raise ValueError('The report filename must not be vendor_accounts.xlsx or contracts.xlsx.')
    if input_folder and Path(input_folder) == Path(output_folder):
        raise ValueError('Invoice input and output folders must be different to avoid reprocessing reports.')
    if input_folder and mdm_folder and Path(input_folder) == Path(mdm_folder):
        raise ValueError('Invoice input and MDM folders must be different; masters are not invoices.')
    if not 0 <= value.rounding_tolerance <= 100 or not 1 <= value.review_threshold <= 100:
        raise ValueError('Review threshold must be 1–100%; rounding tolerance must be 0–100.')
    if mdm_folder:
        vendor_path, contract_path = catalog_paths(Path(mdm_folder), allow_legacy=False)
        if not vendor_path.is_file() or not contract_path.is_file():
            raise ValueError('MDM folder must contain current InvoiceMDM and Contracts CSV/XLSX files whose names contain today\'s YYYYMMDD (legacy vendor_accounts/contracts names are also supported).')
        if not load_vendor_accounts(vendor_path, contract_path):
            raise ValueError('Vendor Accounts master has no usable accounts.')
        # Require a correctly shaped contracts table, without rejecting individual
        # undated/unmatched contracts: those remain visible validation outcomes.
        from services.vendor_matching import read_master_rows
        read_master_rows(contract_path, {'Contract ID', 'Start Date', 'End Date'})
    return replace(value, invoice_input_folder=input_folder, output_folder=output_folder,
                   mdm_folder=mdm_folder, master_excel_filename=filename)


def save_ui_settings(base, value: UiSettings) -> UiSettings:
    value = validate_ui_settings(value)
    value = replace(value, revision=uuid4().hex)
    _atomic_write(settings_file(base.local_storage_dir),
                  json.dumps(asdict(value), ensure_ascii=False, indent=2).encode('utf-8'))
    return value


def configured_storage(base, value: UiSettings | None = None) -> LocalStorage:
    value = value or load_ui_settings(base)
    return LocalStorage(base.local_storage_dir, output_folder=value.output_folder,
                        excel_filename=value.master_excel_filename, mdm_folder=value.mdm_folder)
