"""Extract explicit, non-inline file attachments from RFC 822 email files."""
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from pathlib import PurePosixPath

from services.email_region import email_region
from utils.file_utils import DocumentInput, is_supported


class _HtmlText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {'br', 'p', 'div', 'li'}:
            self.parts.append('\n')

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _region_body(message) -> str:
    part = message.get_body(preferencelist=('plain', 'html'))
    if part is None:
        return ''
    try:
        content = part.get_content()
    except (LookupError, UnicodeError, ValueError):
        return ''
    if part.get_content_type() != 'text/html':
        return content
    parser = _HtmlText()
    parser.feed(content[:32000])
    return ''.join(parser.parts)


def extract_eml_attachments(filename: str, data: bytes, max_file_bytes: int) -> list[DocumentInput]:
    email_name = PurePosixPath(filename.replace('\\', '/')).name
    if len(data) > max_file_bytes:
        raise ValueError(f"EML exceeds the upload size limit: {email_name}")
    try:
        message = BytesParser(policy=policy.default).parsebytes(data)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Cannot read email file: {email_name}") from exc
    region, region_issue = email_region(str(message.get('Subject', '')), _region_body(message))
    documents: list[DocumentInput] = []
    attachment_index = 0
    for part in message.walk():
        if part.is_multipart() or part.get_content_disposition() != 'attachment':
            continue
        attachment_index += 1
        if attachment_index > 200:
            raise ValueError('Email contains more than 200 attachments.')
        original = part.get_filename() or f'attachment-{attachment_index}'
        name = PurePosixPath(original.replace('\\', '/')).name
        # CID resources can be signatures/logos even when marked as attachments.
        if part.get('Content-ID') or part.get('Content-Location'):
            continue
        document = DocumentInput(name, b'', email_name, name, attachment_index)
        document.email_region = region
        document.email_region_issue = region_issue
        if not is_supported(name):
            document.intake_status = 'SKIPPED'
            document.intake_message = 'Unsupported attachment type; only attached PDF and supported image files are processed.'
        else:
            try:
                payload = part.get_payload(decode=True)
                if not payload:
                    raise ValueError('Attachment has no readable file content.')
                if len(payload) > max_file_bytes:
                    raise ValueError('Attachment exceeds the document size limit.')
                document.data = payload
            except (TypeError, ValueError, UnicodeError):
                document.intake_status = 'FAILED'
                document.intake_message = 'Attachment could not be read from the EML file.'
        documents.append(document)
    return documents or [DocumentInput(email_name, b'', source_email=email_name,
                                       intake_status='SKIPPED',
                                       intake_message='No non-inline document attachments found.')]
