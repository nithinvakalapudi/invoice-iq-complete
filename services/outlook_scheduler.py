"""One scheduled intake pass against the current user's classic Outlook profile."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from config.settings import settings
from config.ui_settings import configured_storage, load_ui_settings
from services.outlook_folder import run_outlook_folder


def _record_status(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    temporary.replace(path)


def main() -> int:
    status_path = Path(settings.local_storage_dir) / 'outlook_schedule_status.json'
    status = {'started_at_utc': datetime.now(timezone.utc).isoformat()}
    try:
        ui = load_ui_settings(settings)
        status['folder'] = ui.outlook_invoice_folder
        storage = configured_storage(settings, ui)
        run = run_outlook_folder(
            storage, ui.rounding_tolerance, ui.review_threshold,
            settings.max_file_mb * 1_000_000, source='desktop',
            mailbox=settings.outlook_mailbox, folder_name=ui.outlook_invoice_folder)
        status.update(outcome='completed', mailbox=run.outlook_mailbox,
                      batch_id=run.batch_id,
                      emails_processed=run.desktop_emails_processed,
                      emails_already_processed=run.emails_already_processed,
                      attachments_saved=len(run.results),
                      failed_attachments=sum(item.processing_status == 'FAILED'
                                             for item in run.results),
                      warning_count=len(run.warnings))
        code = 0
    except Exception as exc:
        status.update(outcome='failed', error=f'{type(exc).__name__}: {exc}')
        code = 1
    status['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
    _record_status(status_path, status)
    return code


if __name__ == '__main__':
    sys.exit(main())
