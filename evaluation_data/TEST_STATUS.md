# Public invoice benchmark — incomplete

Configured application model: **gemini-3.7-flash**. Its model metadata endpoint confirmed availability and generateContent support. However, live invoice generation failed; a follow-up diagnostic returned **HTTP 503 UNAVAILABLE**, with Google's message that this model is experiencing high demand. No full benchmark or model training has completed.

## Prepared data

- 1,000 unique invoice images downloaded and byte-hash checked.
- 100 development invoices and 900 held-out test invoices.
- 336 selected invoices have publisher-provided nonblank account-number labels; missing labels are not treated as evidence of absence.
- Public synthetic English invoices with limited layout variety, not a guarantee for future company invoices.

## Evaluated records by model

| Model/run | Evaluated invoices | VALID | REVIEW_REQUIRED | FAILED | SKIPPED | Not tested |
|---|---:|---:|---:|---:|---:|---:|
| gemini-3.7-flash / 3d27c90a2034b6d2 | 1 | 0 | 0 | 1 | 0 | 999 |
| gemini-2.5-flash / 8f4248baa26622d7 | 1 | 0 | 1 | 0 | 0 | 999 |

These are separate model runs on the same single development invoice, not two unique test invoices. The diagnostic request is not an additional evaluated invoice. No held-out invoices have been evaluated.

## Review comments

The 2.5 pilot's comments were line-item mismatches on lines 1–6 and “Line-item total does not equal subtotal.” It extracted gross line totals, whereas the validator compares quantity × net unit price and pre-tax subtotal. Its scored publisher-reference fields matched, including the account number; one sample is insufficient for an accuracy claim. Validation status and reference accuracy measure different things.

The 3.7 pilot's recorded error was “Gemini API request failed. Check network access, model availability, and API configuration.” The separate diagnostic established the 503 high-demand response. Error handling has now been improved to make future 503 messages explicit and stop bulk scheduling during outages.

## Files

Each run's `reports` folder contains `Test_Results.xlsx`, `Invoice_Results.csv`, `Field_Comparisons.csv`, `Status_Summary.csv`, `Review_Reasons.csv`, `Dataset_Inventory.csv`, and `All_Results.json`. The inventory lists every selected invoice, including NOT_TESTED entries. The 3.7 run also includes the provider diagnostic. The app's **Public dataset test results** section exposes the complete per-run downloads and status/review filters.

Saved company invoice data was not used or modified by these tests. No 95%+ accuracy claim is justified by the current pilot.
