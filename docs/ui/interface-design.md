# InvoiceIQ interface design

## Visual direction

A focused, local-first invoice workspace. Deep navy navigation provides a stable anchor;
white cards on a cool neutral canvas separate intake, extraction results, and saved reports.
Teal identifies the primary actions. Green, amber, and red communicate actual success,
review, and failure states without overriding backend validation.

| Role | Color |
| --- | --- |
| Navigation | `#132B40` |
| Workspace canvas | `#F3F6F9` |
| Cards | `#FFFFFF` |
| Primary action | `#087F73` |
| Primary text | `#172D42` |
| Secondary text | `#53667B` |

## Composition

- FLOWSTACK Brick owns controls, typography, spacing, cards, navigation, dialogs, tabs, and tables.
- Appearance uses the public semantic theme contract and documented component tokens.
- App-only styles handle the brand artwork, workflow illustration, notification decoration,
  and responsive visibility of the mobile navigation. No component internals are overridden.
- The desktop Sidebar is sticky with a bounded ScrollArea. Below 960px it is offcanvas;
  visible mobile links provide the same destinations without a modal menu.
- All existing input formats and API handlers remain available. The email intake still
  processes actual supported attachments, not the email body or signature.

## Results and safety

The default overview contains eight essential accounting columns. All fields received
from the backend remain available in the full-details tab. Search and status filters
preserve original batch indices so corrections target the correct invoice. Display-only
amount formatting never changes exported values or MDM data.

History stays collapsed until requested. Both reset confirmations remain, including the
warning that trained models and reviewed examples are retained. Success labels reflect
actual validated results; missing or ambiguous data is never disguised as success.

## Verification

```powershell
cd frontend
npm test
npm run build
```

Backend workflow regression tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_web_app.py -q
```

Manual browser checks include wide and narrow layouts, navigation, empty intake,
collapsed history, opening a saved batch, search, review filtering, all-field switching,
the correction dialog, and cancelling the final reset confirmation. Live Outlook Run
and final data deletion are not triggered by visual QA.

### Verification results — 9 October 2026

- Production build: passed.
- Frontend presentation tests: **10 passed**, covering filtering, correction indices,
  status labels, null/zero handling, unchanged source records, and amount formatting.
- Full Python regression suite: **181 passed**.
- Live browser: verified at 1440px desktop and 390px mobile; no page-level horizontal overflow.
- Saved batch: nine existing records displayed; nine successful, zero review-needed,
  and zero failed. All 39 configured fields were accessible in the full-details view.
- Multi-file picker and removing selected files: passed; processing remains disabled
  when the selection is empty. No additional invoice rows were created for visual QA.
- Search, status filters, saved history, settings, correction dialog, and both reset
  confirmations: passed. Final reset was cancelled; stored invoices and training retained.

Vite emits existing third-party `use client` directive warnings for FLOWSTACK/Zag
packages in a client-only build. They did not prevent the build or the tested UI behavior.
