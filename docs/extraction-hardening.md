# Invoice extraction hardening — 1 November 2026

Current configuration: local OCR and deterministic rules only. Invoice model
loading and automatic retraining have been disabled at the user's request.
No separate model artifacts or model services are needed. The experimental
Qwen downloads were removed. The Kaggle candidate-model results below are
historical experiments, not the active runtime.

Printed invoice dates are now retained exactly in the existing date columns,
including ambiguous numeric strings. No calendar interpretation is guessed
for ageing when date order is unknown. The latest full suite passed 325 tests;
the 11-document upload/MDM/export run passed using `ocr_rules` exclusively.

## Implemented behavior

- Native PDF words and OCR word bounding boxes share a spatial field reader.
  It reads explicit seller/client labels and service/billing date columns.
- A nearby Contract Period column cannot replace conflicting Billing Period
  results. Multiple distinct service periods are kept unresolved for review;
  the plain-text fallback cannot replace them with its first date range.
- Amount Due, Balance Due, Grand Total, Value Added Tax and named-month invoice
  dates are recognized. Net/VAT/Gross summary values must reconcile before
  three positional amounts are assigned. Decimal commas and space-grouped
  amounts are normalized.
- Internal date parsing uses unambiguous numeric-date evidence in each document.
  Display/export retains the date as printed, even when its calendar order is
  unknown. DMY or MDY can be configured for a known input convention.
- If service columns were detected but their values are unreadable, ambiguous
  or conflicting, the invoice requires review instead of asserting that the
  document has no service dates. Invoices without usable service evidence
  remain subject to the existing missing-service-date rejection rule.
- Supplier address remains the region source, as requested. The system does
  not switch to the customer address to obtain a convenient account match.
- Contracts that have not started have `NOT_STARTED` status and are rejected,
  like expired contracts, and excluded from successful delivery exports.
  Contract boundary dates use India time. Invoice service-period coverage
  within a contract is still a separate business rule.
- An explicitly configured MDM folder requires today's dated InvoiceMDM and
  contracts exports, with no silent fallback to an undated file. Direct legacy
  service calls and the internal legacy/demo catalog remain supported.
- Master headers accept case, spacing, underscore and punctuation variations,
  plus explicit aliases such as vendor name and contract number. Duplicate
  normalized headers are rejected.
- Runtime model loading is disabled. `/api/config` retains the compatibility
  `model_diagnostics` key and reports `models_enabled: false` and OCR status.
- `requirements-windows.lock.txt` records the installed runtime dependencies,
  including transitives. `scripts/export_runtime_lock.py` regenerates the list.
  Saved historical model files remain untouched but are not loaded. Model
  packages were moved out of the application's runtime requirements.

## Dataset work

Source: https://www.kaggle.com/datasets/osamahosamabdellatif/high-quality-invoice-images-for-ocr

The downloaded first CSV contains 499 JSON labels and OCR transcripts. Its SHA256
is `2480ee3ffc40578f954d02649147fd09be97795ed3290f8e56a7f8807a886477`.
The dataset is approximately 1.22 GB in total; only a selected image sample is
downloaded locally. Dataset files, model candidates and per-document results
remain in ignored `evaluation_data/kaggle_sample`.

Reproduce the evaluation and fit a separate candidate with:

```powershell
.\.venv\Scripts\python.exe -m evaluation.kaggle_invoices --limit 60 --train
```

Images are ordered deterministically by filename hash. Every fifth image is
excluded from fitting; the JSON report records the split and exact field counts.
The first six held-out images were used during parser development and are a
development check, not an independent accuracy estimate. They produced exact
seller, client, invoice number, total and tax matches on all six; four invoice
dates were resolved and two ambiguous dates were left blank.

The annotations do not supply service periods, billing region, MDM accounts or
contracts. They cannot establish correctness for those workflow fields. A
candidate trained on 24 of the images did not improve the extractor on the six
development images and was not installed. The extended run used 60 images,
48 for candidate fitting and 12 held out of fitting. Seller, client, invoice
number, total and tax matched on 12/12 each. Invoice dates matched on 7/12;
the other five were blank with explicit date-order ambiguity reasons. The six
new holdout images were not used for parser tuning. All come from one batch,
so these are sample results, not a general invoice-accuracy estimate. The
48-image candidate did not improve these outcomes and was not installed.
The machine-readable report is `evaluation_data/kaggle_sample/evaluation.json`.

## Verification boundaries

The full application suite passed with 319 tests during hardening. A subsequent
service-heading/invoice-date safeguard passed a 37-test focused extraction run.
Reconstructed PDF tests cover distinct contract/billing columns,
split service headers, conflicts, date interpretation, future contracts,
header aliases and strict daily catalog selection.

This work improves the local pipeline; it does not replace it with a foundation
document model or prove universal layout coverage. The original failing PDF/email
attachments have not been supplied locally, so those four source files remain
unverified. The supplied photographs are layout references, not substitutes for
the PDF text, full pages and original image quality.
