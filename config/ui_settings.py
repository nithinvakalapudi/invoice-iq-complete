"""Persistent user-editable locations; never move the history DB or trained models."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from uuid import uuid4

from services.local_storage import LocalStorage, _atomic_write


@dataclass(frozen=True)
class UiSettings:
    invoice_input_folder: str = ''
    outlook_invoice_folder: str = 'Invoices'
    output_folder: str = ''
    master_excel_filename: str = 'Invoice_History.xlsx'
    mdm_folder: str = ''
    review_threshold: float = 95
    rounding_tolerance: float = .02
    revision: str = ''


def settings_file(root: Path | str) -> Path:
    return Path(root).resolve() / 'ui_settings.json'


def load_ui_settings(base) -> UiSettings:
    defaults = UiSettings(outlook_invoice_folder=base.outlook_invoice_folder,
                          output_folder=str(Path(base.local_storage_dir).resolve()),
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
    outlook_folder = value.outlook_invoice_folder.strip().strip('"')
    if not outlook_folder or len(outlook_folder) > 255 or '/' in outlook_folder or '\\' in outlook_folder:
        raise ValueError('Outlook invoice folder must be one folder name, such as Invoices.')
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
    # Save locations independently of whether today's MDM exports are present
    # or parseable. Availability is checked when MDM matching runs.
    return replace(value, invoice_input_folder=input_folder, outlook_invoice_folder=outlook_folder,
                   output_folder=output_folder,
                   mdm_folder=mdm_folder, master_excel_filename=filename)


def save_ui_settings(base, value: UiSettings) -> UiSettings:
    value = validate_ui_settings(value)
    value = replace(value, revision=uuid4().hex)
    path = settings_file(base.local_storage_dir)
    encoded = json.dumps(asdict(value), ensure_ascii=False, indent=2).encode('utf-8')
    _atomic_write(path, encoded)
    # Fail the request if persistence did not actually stick; the UI must not
    # report a successful save for a path that would revert on refresh.
    saved = json.loads(path.read_text(encoding='utf-8'))
    if saved != asdict(value):
        raise OSError(f'Settings verification failed for {path}.')
    return value


def configured_storage(base, value: UiSettings | None = None) -> LocalStorage:
    value = value or load_ui_settings(base)
    return LocalStorage(base.local_storage_dir, output_folder=value.output_folder,
                        excel_filename=value.master_excel_filename, mdm_folder=value.mdm_folder)
