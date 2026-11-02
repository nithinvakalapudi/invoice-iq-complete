# Review-status test — 2026-10-09

The local extraction pipeline was changed to avoid automatic review solely because its field-confidence score is uncalibrated. A local invoice now needs all required fields, printed net/tax/total, complete service lines, reconciled amounts, no derived net amount, and no validation error to pass the rule checks. A rule pass is **not** a claim of 95% extraction accuracy or independent verification. Duplicates, OCR-only results, missing required fields, amount mismatches, incomplete service lines and derived net amounts still require review.

## Test results

- Full Python suite: **151 passed**.
- React production build: **passed**.
- Supplied 10-PDF labeled archive, processed without changing saved history: **8 SUCCESS / No Review Required**, **2 REVIEW_REQUIRED**.
- The two invoices still requiring review are `invoice_06_GDM-260913.pdf` and `invoice_08_PLF-SG-261024.pdf`; neither yielded a required invoice date.
- The other eight had complete required fields, net/tax/total and service lines, with no validation errors.
- The MDM Billing Account lookup remains separate from review classification. A blank Billing Account is not treated as a missing required invoice field.

| Source invoice | Review result | Reason if review is required |
| --- | --- | --- |
| invoice_01_BOT-2026-1001.pdf | SUCCESS | — |
| invoice_02_NDS-INV-26042.pdf | SUCCESS | — |
| invoice_03_VCA-26-27-0187.pdf | SUCCESS | — |
| invoice_04_HP-2026-774.pdf | SUCCESS | — |
| invoice_05_SOS-INV-26155.pdf | SUCCESS | — |
| invoice_06_GDM-260913.pdf | REVIEW_REQUIRED | Invoice Date missing |
| invoice_07_EMS-2026-0918.pdf | SUCCESS | — |
| invoice_08_PLF-SG-261024.pdf | REVIEW_REQUIRED | Invoice Date missing |
| invoice_09_CPS-2026-1048.pdf | SUCCESS | — |
| invoice_10_BRE-INV-2026-311.pdf | SUCCESS | — |

The earlier end-to-end report is a pre-change baseline and should not be used as the current review-status result.
