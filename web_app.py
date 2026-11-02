"""Local web API for the FLOWSTACK interface; the extraction services remain shared."""
from __future__ import annotations

import json
import csv
import secrets
from datetime import datetime, timedelta, timezone
from html import escape
from dataclasses import asdict
from pathlib import Path
from threading import Lock
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from config.settings import settings
from config.ui_settings import (UiSettings, configured_storage, load_ui_settings,
                                save_ui_settings, validate_ui_settings)
from evaluation.reporting import export_run, invoice_rows, load_run, status_counts
from models.invoice_schema import INVOICE_FIELDS, InvoiceResult
from services.csv_service import build_zip, generate_csvs
from services.document_processing import process_document
from services.duplicate_service import mark_duplicates
from services.local_storage import APPROVED_EXCEL_NAME, LocalStorage, _excel_bytes
from services.local_extraction_service import extraction_ready, model_diagnostics
from services.outlook_folder import run_outlook_folder
from services.mdm_csv_service import (DISPLAY_COLUMNS as MDM_COLUMNS, LEGACY_DRAFT_WARNING,
                                      REPORT_NAME as MDM_REPORT_NAME, VERIFIED_REPORT_NAME,
                                      generate_mdm_csv, generate_verified_csv, mdm_row)
from services.vendor_matching import catalog_paths, load_vendor_accounts
from services.invoice_folder import run_invoice_folder, save_upload_batch
from services.hosted_bridge import bridge_token, hosted_origin
from services.storage_lock import folder_operation_lock
from services.tabular_intake import import_invoice_rows
from services.validation_service import (REQUIRED_FIELDS, REQUIRED_FIELD_LABELS,
                                         effective_errors, effective_validation_status,
                                         service_date_rejection_reason, validate_invoice)

app = FastAPI(title="Invoice Intelligence")
_reset_lock = Lock()
_reset_tokens: dict[str, tuple[str, str]] = {}
_root = Path(__file__).resolve().parent
_dist = _root / "frontend" / "dist"


@app.middleware('http')
async def hosted_interface_access(request: Request, call_next):
    """Permit the approved Pages UI to call only this computer's local API."""
    origin = request.headers.get('origin', '')
    approved = hosted_origin(Path(settings.local_storage_dir))
    if request.url.path.startswith('/api/') and approved and origin == approved:
        headers = {
            'Access-Control-Allow-Origin': approved,
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Authorization, Content-Type',
            'Access-Control-Expose-Headers': 'Content-Disposition',
            'Access-Control-Max-Age': '600',
            'Vary': 'Origin',
            'Cache-Control': 'no-store',
        }
        if request.headers.get('access-control-request-private-network') == 'true':
            headers['Access-Control-Allow-Private-Network'] = 'true'
        if request.method == 'OPTIONS':
            return Response(status_code=204, headers=headers)
        expected = 'Bearer ' + bridge_token(Path(settings.local_storage_dir))
        if not secrets.compare_digest(request.headers.get('authorization', ''), expected):
            return JSONResponse({'detail': 'Connect this computer to the hosted interface.'},
                                status_code=401, headers=headers)
        response = await call_next(request)
        response.headers.update(headers)
        return response
    return await call_next(request)


@app.get('/bridge/pair')
def pair_hosted_interface(request: Request):
    """Send a local secret to the one approved Pages origin via postMessage."""
    if request.url.hostname not in {'127.0.0.1', 'localhost'}:
        raise HTTPException(403, 'Open this page on the computer running the app.')
    approved = hosted_origin(Path(settings.local_storage_dir))
    if not approved:
        raise HTTPException(404, 'No hosted interface is configured on this computer.')
    token = bridge_token(Path(settings.local_storage_dir))
    nonce = secrets.token_urlsafe(16)
    script = ("if (window.opener) { window.opener.postMessage("
              + json.dumps({'type': 'invoice-local-connection', 'token': token})
              + ', ' + json.dumps(approved) + "); window.close(); }"
              + "else { document.getElementById('message').textContent = "
              + json.dumps('Return to the hosted InvoiceIQ tab and select Connect again.') + '; }')
    page = ("<!doctype html><html lang='en'><meta charset='utf-8'>"
            "<title>Connect InvoiceIQ</title><body>"
            "<h1>Connecting InvoiceIQ</h1><p id='message'>This window should close automatically.</p>"
            f"<script nonce='{escape(nonce)}'>{script}</script></body></html>")
    return HTMLResponse(page, headers={
        'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
        'X-Frame-Options': 'DENY',
        'Content-Security-Policy': f"default-src 'none'; script-src 'nonce-{nonce}'; frame-ancestors 'none'",
    })


def storage() -> LocalStorage:
    return configured_storage(settings)


def _same_origin(request: Request) -> None:
    """Block browser cross-site writes to the local-only service."""
    origin = request.headers.get("origin")
    if origin and origin not in {f"{request.url.scheme}://{request.url.netloc}",
                                hosted_origin(Path(settings.local_storage_dir))}:
        raise HTTPException(403, "Cross-origin request refused")


def _download_filename(name: str, now: datetime | None = None) -> str:
    """Timestamp spreadsheet downloads in the user's India local time."""
    base = Path(name).name
    stem, suffix = Path(base).stem, Path(base).suffix
    if suffix.casefold() not in {'.csv', '.xlsx'}:
        return base
    local = (now or datetime.now(timezone.utc)).astimezone(timezone(timedelta(hours=5, minutes=30)))
    stamp = f"{local:%m-%d-%Y}_{local.strftime('%I').lstrip('0') or '12'}-{local:%M}_{local:%p}"
    return f'{stem}_{stamp}{suffix}'


def _batch(storage_instance: LocalStorage, batch_id: str) -> list[InvoiceResult]:
    try:
        storage_instance._batch_path(batch_id)
    except ValueError as exc:
        raise HTTPException(404, "Batch not found") from exc
    for known_id, results in storage_instance.load_batches():
        if known_id == batch_id:
            return results
    raise HTTPException(404, "Batch not found")


def _counts(results: list[InvoiceResult], vendor_accounts=None) -> dict[str, int]:
    statuses = [effective_validation_status(result) for result in results]
    mdm_statuses = ([mdm_row(result, vendor_accounts)['Review status'] for result in results]
                    if vendor_accounts is not None else None)
    review_flags = ([status == 'REVIEW_REQUIRED' for status in mdm_statuses] if mdm_statuses is not None else
                    [result.review_required and status != 'REJECTED'
                     for result, status in zip(results, statuses)])
    return {
        "total": len(results),
        # Count completed document extraction, including review-only drafts.
        # Approval is a separate decision; otherwise a fully processed batch
        # misleadingly displays "Processed 0".
        "processed": sum(r.processing_status in {"PROCESSED", "OCR_ONLY", "LOCAL_DRAFT"}
                         for r in results),
        "auto_approved": (mdm_statuses.count('SUCCESS') if mdm_statuses is not None else
                          sum(status == "VALID" and not review
                              for status, review in zip(statuses, review_flags))),
        "ocr_only": sum(r.processing_status == "OCR_ONLY" for r in results),
        "local_draft": sum(r.processing_status == "LOCAL_DRAFT" for r in results),
        "imported": sum(r.processing_status == "IMPORTED" for r in results),
        "review": sum(review_flags),
        "rejected": (mdm_statuses.count('REJECTED') if mdm_statuses is not None else statuses.count('REJECTED')),
        "failed": sum(r.processing_status == "FAILED" for r in results),
        "duplicate": sum(r.duplicate_status == "POSSIBLE_DUPLICATE" for r in results),
    }


def _result_payload(result: InvoiceResult, vendor_accounts=None) -> dict:
    payload = asdict(result)
    payload['invoice'].update(result.printed_dates)
    payload['validation_status'] = effective_validation_status(result)
    payload['errors'] = effective_errors(result)
    payload['review_required'] = result.review_required or bool(service_date_rejection_reason(result))
    payload['warnings'] = [warning for warning in payload['warnings']
                           if warning != LEGACY_DRAFT_WARNING]
    return {**payload, "mdm_row": mdm_row(result, vendor_accounts)}


@app.get("/api/config")
def config():
    ui = load_ui_settings(settings)
    try:
        s = storage()
        outlook_folder = str(s.outlook_folder)
        batches, records = s.count()
        warnings = s.export_warnings()
        generation = s.generation
        available = True
    except Exception as exc:
        batches = records = 0
        warnings = [f"Local storage unavailable: {exc}"]
        generation = ""
        available = False
        outlook_folder = ""
    mdm_folder, vendor_file = ui.mdm_folder, ''
    if available:
        try:
            mdm_folder = str(s.vendor_catalog_folder())
            vendor_file = str(catalog_paths(Path(mdm_folder), allow_legacy=s.mdm_folder is None)[0])
        except (OSError, ValueError) as exc:
            # Keep Settings and history accessible when the chosen master is bad.
            warnings.append(f'MDM folder needs attention: {exc}')
    diagnostics = model_diagnostics()
    warnings.extend(f'Extraction {name}: {issue}' for name, issue in diagnostics['issues'].items())
    return {
        "model": 'Local OCR and invoice parsing',
        "model_diagnostics": diagnostics,
        "mdm_columns": MDM_COLUMNS,
        "required_fields": [REQUIRED_FIELD_LABELS[name] for name in REQUIRED_FIELDS],
        "api_ready": extraction_ready(),
        "intake_ready": available,
        "extraction_backend": settings.extraction_backend,
        "setup_message": ('' if extraction_ready() else
                          'OCR parsing is unavailable. Review every field and check the local OCR installation. No model download or remote request is made.'),
        "storage_ready": available,
        "generation": generation,
        "max_file_mb": settings.max_file_mb,
        "default_tolerance": ui.rounding_tolerance,
        "minimum_field_confidence": ui.review_threshold,
        "ui_settings": {**asdict(ui), "mdm_folder": mdm_folder},
        "batches": batches,
        "records": records,
        "reviewed_training_examples": len(s.training_examples()) if available else 0,
        "warnings": warnings,
        "outlook_folder": outlook_folder,
        "outlook_invoice_folder": ui.outlook_invoice_folder,
        "outlook_mailbox": settings.outlook_mailbox,
        "vendor_accounts_file": vendor_file,
        "cumulative_invoice_report_file": str(s.output_folder / MDM_REPORT_NAME) if available else '',
    }


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    invoice_input_folder: str = ''
    outlook_invoice_folder: str = 'Invoices'
    output_folder: str
    master_excel_filename: str
    mdm_folder: str = ''
    review_threshold: float = Field(ge=1, le=100)
    rounding_tolerance: float = Field(ge=0, le=100)
    revision: str = ''


@app.post('/api/settings')
def update_settings(payload: SettingsUpdate, request: Request):
    _same_origin(request)
    try:
        with folder_operation_lock(Path(settings.local_storage_dir)):
            current = load_ui_settings(settings)
            if payload.revision != current.revision:
                raise HTTPException(409, 'Settings changed in another window. Reload before saving.')
            new = validate_ui_settings(UiSettings(**payload.model_dump()))
            # Probe output write permission before changing the durable settings.
            from tempfile import TemporaryFile
            destination = Path(new.output_folder)
            destination.mkdir(parents=True, exist_ok=True)
            with TemporaryFile(dir=destination):
                pass
            new = save_ui_settings(settings, new)
            warnings = configured_storage(settings, new).refresh_exports()
    except (OSError, ValueError, RuntimeError, csv.Error) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {'ui_settings': asdict(new), 'warnings': warnings,
            'message': 'Settings saved. Reports use the selected output folder; history and trained models were kept.'}


@app.get("/api/history")
def history():
    s = storage()
    batches = s.load_batches()
    vendor_accounts = s.vendor_accounts()
    return {
        "generation": s.generation,
        "batches": [
            {"id": batch_id, "counts": _counts(results, vendor_accounts), "sources": [r.source_file for r in results[:3]]}
            for batch_id, results in reversed(batches)
        ],
        "report_files": list(s.report_files()),
        "warnings": s.export_warnings(),
    }


@app.post("/api/history/refresh")
def refresh(request: Request):
    _same_origin(request)
    return {"warnings": storage().refresh_exports()}


class MdmRunRequest(BaseModel):
    batch_id: str
    generation: str


def _mdm_summary(rows: list[dict]) -> dict[str, int]:
    statuses = [row['Billing Account match status'] for row in rows]
    contracts = [row['Contract check status'] for row in rows]
    return {
        'matched': statuses.count('MATCHED'),
        'low_confidence': statuses.count('LOW_CONFIDENCE'),
        'not_found': statuses.count('NOT_FOUND'),
        'contracts_present': contracts.count('PRESENT'),
        'contracts_missing_or_invalid': sum(status in {
            'NOT_FOUND', 'MISSING_DATES', 'INVALID_DATES', 'INVALID_MASTER', 'EXPIRED'
        } for status in contracts),
    }


@app.post("/api/mdm/run")
def run_mdm(payload: MdmRunRequest, request: Request):
    """Re-match saved invoices to the current MDM master and rebuild reports."""
    _same_origin(request)
    s = storage()
    if payload.generation != s.generation:
        raise HTTPException(409, "Local data changed. Reload the page before running MDM.")
    results = _batch(s, payload.batch_id)
    folder = s.vendor_catalog_folder()
    try:
        catalog, contracts = catalog_paths(folder, allow_legacy=s.mdm_folder is None)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not catalog.is_file():
        raise HTTPException(422, "MDM/vendor_accounts.csv is missing")
    try:
        accounts = load_vendor_accounts(catalog, contracts)
    except (OSError, UnicodeError, ValueError, csv.Error) as exc:
        raise HTTPException(422, f"Invalid Vendor Accounts master: {exc}") from exc
    if not accounts:
        raise HTTPException(422, "Vendor Accounts master has no usable accounts")
    for result in results:
        result.mdm_checked = True
    try:
        warnings = s.save_batch(payload.batch_id, results)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(409, f"Could not refresh MDM reports: {exc}") from exc
    rows = [mdm_row(result, accounts) for result in results]
    return {
        "batch_id": payload.batch_id,
        "generation": s.generation,
        "counts": _counts(results, accounts),
        "results": [_result_payload(result, accounts) for result in results],
        "mdm_summary": _mdm_summary(rows),
        "warnings": warnings,
    }


@app.post('/api/mdm/check')
def check_mdm(payload: MdmRunRequest, request: Request):
    """Read-only verification of the MDM stage against the current master files."""
    _same_origin(request)
    s = storage()
    if payload.generation != s.generation:
        raise HTTPException(409, 'Local data changed. Reload before checking MDM.')
    results = _batch(s, payload.batch_id)
    if not results or any(result.mdm_checked is not True for result in results):
        raise HTTPException(409, 'Run MDM for this batch before checking it.')
    try:
        catalog, contracts = catalog_paths(s.vendor_catalog_folder(), allow_legacy=s.mdm_folder is None)
        accounts = load_vendor_accounts(catalog, contracts)
    except (OSError, UnicodeError, ValueError, csv.Error) as exc:
        raise HTTPException(422, f'MDM master could not be checked: {exc}') from exc
    if not accounts:
        raise HTTPException(422, 'Vendor Accounts master has no usable accounts')
    rows = [mdm_row(result, accounts) for result in results]
    return {'batch_id': payload.batch_id, 'generation': s.generation,
            'mdm_summary': _mdm_summary(rows), 'rows': rows}


class FolderRunSettings(BaseModel):
    tolerance: float = Field(ge=0, le=100)
    threshold: float = Field(ge=1, le=100)
    source: Literal['local', 'desktop', 'both'] = 'local'


@app.post("/api/outlook/run")
def outlook_run(payload: FolderRunSettings, request: Request):
    _same_origin(request)
    s = storage()
    ui = load_ui_settings(settings)
    try:
        run = run_outlook_folder(s, payload.tolerance, payload.threshold,
                                 settings.max_file_mb * 1_000_000,
                                 source=payload.source, mailbox=settings.outlook_mailbox,
                                 folder_name=ui.outlook_invoice_folder)
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc
    vendor_accounts = s.vendor_accounts()
    return {"folder": str(run.folder), "batch_id": run.batch_id,
            "emails_processed": run.emails_processed,
            "desktop_emails_processed": run.desktop_emails_processed,
            "desktop_messages_scanned": run.desktop_messages_scanned,
            "local_emails_processed": run.local_emails_processed,
            "outlook_mailbox": run.outlook_mailbox,
            "emails_already_processed": run.emails_already_processed,
            "ignored_files": run.ignored_files, "counts": _counts(run.results, vendor_accounts),
            "results": [_result_payload(result, vendor_accounts) for result in run.results], "warnings": run.warnings,
            "generation": s.generation}


@app.post("/api/process")
async def process(
    request: Request,
    files: list[UploadFile] = File(...),
    tolerance: float | None = Form(None),
    threshold: float | None = Form(None),
):
    _same_origin(request)
    ui = load_ui_settings(settings)
    tolerance = ui.rounding_tolerance if tolerance is None else tolerance
    threshold = ui.review_threshold if threshold is None else threshold
    if not 0 <= tolerance <= 100 or not 1 <= threshold <= 100:
        raise HTTPException(422, "Invalid processing settings")
    if len(files) > 100:
        raise HTTPException(413, "Select at most 100 source files per batch")
    max_bytes = settings.max_file_mb * 1_000_000
    uploads: list[tuple[str, bytes]] = []
    for item in files:
        data = await item.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise HTTPException(413, f"{item.filename} exceeds {settings.max_file_mb} MB")
        uploads.append((item.filename or "upload", data))
    if not uploads:
        raise HTTPException(422, "Select at least one file")
    s = storage()
    try:
        with folder_operation_lock(s.root):
            batch_id, results, warnings = save_upload_batch(
                s, uploads, tolerance, threshold, max_bytes, process_document, import_invoice_rows)
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc
    vendor_accounts = s.vendor_accounts()
    return {"batch_id": batch_id, "generation": s.generation, "counts": _counts(results, vendor_accounts),
            "results": [_result_payload(r, vendor_accounts) for r in results], "warnings": warnings}


@app.post('/api/input-folder/run')
def input_folder_run(request: Request):
    _same_origin(request)
    ui = load_ui_settings(settings)
    if not ui.invoice_input_folder:
        raise HTTPException(422, 'Set an Invoice input folder in Settings, or use manual upload.')
    s = storage()
    try:
        batch_id, results, warnings, already, ignored = run_invoice_folder(
            s, ui.invoice_input_folder, ui.rounding_tolerance, ui.review_threshold,
            settings.max_file_mb * 1_000_000, process_document, import_invoice_rows)
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc
    accounts = s.vendor_accounts()
    return {'batch_id': batch_id, 'generation': s.generation, 'counts': _counts(results, accounts),
            'results': [_result_payload(result, accounts) for result in results], 'warnings': warnings,
            'already_processed': already, 'ignored_files': ignored}


@app.get("/api/batches/{batch_id}")
def get_batch(batch_id: str):
    s = storage()
    results = _batch(s, batch_id)
    vendor_accounts = s.vendor_accounts()
    return {"batch_id": batch_id, "generation": s.generation, "counts": _counts(results, vendor_accounts),
            "results": [_result_payload(r, vendor_accounts) for r in results]}


class Correction(BaseModel):
    generation: str
    index: int = Field(ge=0)
    fields: dict[str, str | float | None]
    tolerance: float = Field(ge=0, le=100)
    threshold: float = Field(ge=1, le=100)


@app.post("/api/batches/{batch_id}/review")
def review(batch_id: str, correction: Correction, request: Request):
    _same_origin(request)
    s = storage()
    if correction.generation != s.generation:
        raise HTTPException(409, "Storage was reset; reload this page")
    results = _batch(s, batch_id)
    if correction.index >= len(results):
        raise HTTPException(404, "Invoice not found")
    result = results[correction.index]
    if result.processing_status == "FAILED":
        raise HTTPException(422, "Failed documents must be re-uploaded")
    if set(correction.fields) - set(INVOICE_FIELDS):
        raise HTTPException(422, "Unknown invoice field")
    for key, value in correction.fields.items():
        setattr(result.invoice, key, value if value not in ("", None) else None)
        result.printed_dates.pop(key, None)
    # The dialog explicitly confirms the displayed values against their source.
    result.extraction_issues = []
    if 'region' in correction.fields and correction.fields['region'] not in (None, ''):
        # An explicit human correction resolves conflicting email/invoice
        # metadata; other field edits must not silently clear that conflict.
        result.region_match_issue = ''
    validate_invoice(result, correction.tolerance, correction.threshold)
    # Saving this dialog is an explicit human verification of the visible fields.
    # It does not manufacture a model-confidence score for later invoices.
    if not result.errors:
        result.review_required = False
        result.validation_status = "VALID"
        result.warnings = [warning for warning in result.warnings
                           if not warning.startswith("Low-confidence extraction")]
    prior_results = [prior for known_id, batch_results in s.load_batches()
                     if known_id != batch_id for prior in batch_results]
    mark_duplicates(results, prior_results)
    warnings = s.save_batch(batch_id, results)
    vendor_accounts = s.vendor_accounts()
    remembered = False
    retrained = False
    if result.processing_status != 'IMPORTED':
        try:
            remembered = s.remember_review(batch_id, correction.index, result)
            if not remembered:
                warnings.append('Correction saved, but no unique source attachment was available for training memory.')
        except (OSError, ValueError, RuntimeError) as exc:
            warnings.append(f'Correction saved, but source text could not be retained: {exc}')
    return {"batch_id": batch_id, "generation": s.generation,
            "training_example_saved": remembered, "model_retrained": retrained,
            "counts": _counts(results, vendor_accounts),
            "results": [_result_payload(r, vendor_accounts) for r in results], "warnings": warnings}


@app.get("/api/download/batch/{batch_id}/{name:path}")
def batch_download(batch_id: str, name: str):
    s = storage()
    results = _batch(s, batch_id)
    files = generate_csvs(results)
    files[MDM_REPORT_NAME] = generate_mdm_csv(results, s.vendor_accounts(), success_only=True)
    files[VERIFIED_REPORT_NAME] = generate_verified_csv(results, s.vendor_accounts())
    if name == APPROVED_EXCEL_NAME:
        payload = _excel_bytes({VERIFIED_REPORT_NAME: files[VERIFIED_REPORT_NAME]})
        media = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    elif name == "invoice_results.zip":
        payload, media = build_zip(files), "application/zip"
    elif name in files:
        payload, media = files[name], "text/csv; charset=utf-8"
    else:
        raise HTTPException(404, "Report not found")
    return Response(payload, media_type=media, headers={"Content-Disposition": f'attachment; filename="{_download_filename(name)}"'})


@app.get("/api/download/history/{name:path}")
def history_download(name: str):
    store = storage()
    # Ageing is an as-of-today measure; refresh before each download so a
    # report saved yesterday cannot be handed out with yesterday's age.
    warnings = store.refresh_exports()
    if warnings:
        raise HTTPException(409, 'Reports could not be refreshed: ' + '; '.join(warnings))
    files = store.report_files()
    if name not in files:
        raise HTTPException(404, "Report not found")
    media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if name.endswith(".xlsx") else "text/csv; charset=utf-8"
    return Response(files[name], media_type=media, headers={"Content-Disposition": f'attachment; filename="{_download_filename(name)}"'})


@app.get("/api/tests")
def tests_list():
    root = _root / "evaluation_data" / "runs"
    runs = []
    for db in sorted(root.glob("*/predictions.sqlite3"), key=lambda p: p.stat().st_mtime, reverse=True):
        metadata, records = load_run(db.parent)
        runs.append({"id": db.parent.name, "model": metadata.get("model", "Unknown model"),
                     "attempted": len(records), "counts": status_counts(records),
                     "diagnostic": (db.parent / "provider_diagnostic.json").is_file()})
    return {"runs": runs}


@app.get("/api/tests/{run_id}")
def test_run(run_id: str, limit: int = 100, offset: int = 0):
    if not run_id.isalnum() or len(run_id) > 80:
        raise HTTPException(404, "Run not found")
    folder = _root / "evaluation_data" / "runs" / run_id
    if not (folder / "predictions.sqlite3").is_file():
        raise HTTPException(404, "Run not found")
    metadata, records = load_run(folder)
    rows = invoice_rows(records)
    return {"metadata": metadata, "counts": status_counts(records), "total": len(rows),
            "rows": rows[max(offset, 0):max(offset, 0) + min(max(limit, 1), 500)],
            "diagnostic": json.loads((folder / "provider_diagnostic.json").read_text(encoding="utf-8"))
            if (folder / "provider_diagnostic.json").is_file() else None}


@app.get("/api/download/tests/{run_id}/{name}")
def test_download(run_id: str, name: str):
    if not run_id.isalnum() or len(run_id) > 80:
        raise HTTPException(404, "Run not found")
    folder = _root / "evaluation_data" / "runs" / run_id
    if not (folder / "predictions.sqlite3").is_file():
        raise HTTPException(404, "Run not found")
    _, _, reports = export_run(folder)
    if name == "Test_Results.zip":
        payload, media = build_zip(reports), "application/zip"
    elif name in reports:
        payload = reports[name]
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if name.endswith(".xlsx") else "text/csv; charset=utf-8"
    else:
        raise HTTPException(404, "Report not found")
    return Response(payload, media_type=media, headers={"Content-Disposition": f'attachment; filename="{_download_filename(name)}"'})


@app.post("/api/reset/prepare")
def reset_prepare(request: Request):
    _same_origin(request)
    s = storage()
    token = secrets.token_urlsafe(32)
    with _reset_lock:
        _reset_tokens.clear()
        _reset_tokens[token] = (str(s.root), s.generation)
    return {"token": token, "generation": s.generation}


class ResetRequest(BaseModel):
    token: str
    generation: str
    confirmation: str


@app.post("/api/reset")
def reset(payload: ResetRequest, request: Request):
    _same_origin(request)
    if payload.confirmation != "CLEAR SAVED INVOICES":
        raise HTTPException(422, "Final confirmation is required")
    with _reset_lock:
        expected = _reset_tokens.pop(payload.token, None)
    s = storage()
    if expected != (str(s.root), s.generation) or payload.generation != s.generation:
        raise HTTPException(409, "Reset confirmation expired or storage changed")
    try:
        return s.reset(str(s.root))
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc


if _dist.is_dir():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/")
    def index():
        return FileResponse(_dist / "index.html")
