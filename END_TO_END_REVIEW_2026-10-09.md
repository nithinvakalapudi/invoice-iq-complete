# Invoice application end-to-end review — 2026-10-09

This is an isolated, read-only review of the supplied `invoices_training_corrected.zip` (first 10 labeled PDFs) and `outlook_invoice_mails_like_reference.zip` (2 `.msg` files). The 10 PDFs were processed through the real local extraction pipeline. The `.msg` files were expanded through the real upload parser. No test invoice was added to the user's saved history, and the MDM master was not changed.

## Step review

| Step | Result | Evidence / limitation |
| --- | --- | --- |
| Archive intake | Pass | 10 labeled PDFs read from the supplied ZIP. |
| PDF reading and local extraction | Partial | All 10 produced `LOCAL_DRAFT` records; none failed to process. |
| Seven-field reference comparison | Partial | 67/70 exact/normalized matches (95.7%): vendor 10/10, invoice number 9/10, invoice date 8/10, currency 10/10, net/subtotal 10/10, tax 10/10, total 10/10. This is only a comparison on these seven fields, not model confidence or overall invoice accuracy. |
| Business Unit	Vendor -As per MDM	Billing Account	Invoice Number (As per Invoice)	Invoice Number	Invoice Date	Currency	Billing Start Date	Billing End Date	Net Amount	Tax Amount	Invoice Received Date	Sent for Scanning Date	Owner	Scanned Date in Expense	Ageing (In Days)	Ageing (Today-Sent For Scanning Date)	Comments
Business Unit	Vendor -As per MDM	Billing Account	Invoice Number (As per Invoice)	Invoice Number	Invoice Date	Currency	Billing Start Date	Billing End Date	Net Amount	Tax Amount	Invoice Received Date	Sent for Scanning Date	Owner	Scanned Date in Expense	Ageing (In Days)	Ageing (Today-Sent For Scanning Date)	Comments
Business Unit	Vendor -As per MDM	Billing Account	Invoice Number (As per Invoice)	Invoice Number	Invoice Date	Currency	Billing Start Date	Billing End Date	Net Amount	Tax Amount	Invoice Received Date	Sent for Scanning Date	Owner	Scanned Date in Expense	Ageing (In Days)	Ageing (Today-Sent For Scanning Date)	Comments
Needs work | 10/10 remain `REVIEW_REQUIRED` because local extraction has no calibrated field confidence. Two also lack a required invoice date. |
| MDM Billing Account | Needs work | 0/10 matched. Blue Ocean's extracted vendor region is West Palm Beach, FL, while the MDM rows are restricted to APAC; the other nine reference vendors are not in the current MDM master. Even with APAC as region, Blue Ocean has five matching account rows and would remain ambiguous without another discriminator. |
| CSV schema | Pass | Generated test CSV has 10 rows and the exact 18 requested columns in order. Blank values remain blank; zero tax remains zero. |
| Persistent storage and reset | Pass in automated tests | Tests cover cumulative append, correction, download, Excel export and reset in isolated temporary storage. The user's live history was not reset or changed. |
| Supplied Outlook `.msg` files | Fail as source files | Both files contain no readable email or attachment content, so each produces a clear `FAILED` result. The valid `.msg` fixture tests pass, but these two supplied files must be re-saved from the original Outlook messages. |
| Frontend and live service | Pass | React production build succeeded. Live home and API responded; live cumulative download has 122 saved rows and 18 columns. |
| Full automated suite | Pass | 145 Python tests passed. |

## Per-invoice final review data

All rows below are `LOCAL_DRAFT` and `REVIEW_REQUIRED`; none were auto-approved. Amounts are extracted net and tax values. The supplied answer sheet was used only for the indicated field comparisons.

| Invoice | Vendor | Invoice date extracted | Currency | Net | Tax | Reference mismatch / extra review reason | MDM match |
| --- | --- | --- | --- | ---: | ---: | --- | --- |
| BOT-2026-1001 | Blue Ocean Technologies, LLC | 10/01/2026 | USD | 4,500.00 | 0.00 | No mismatch in seven checked fields; uncalibrated local draft | LOW_CONFIDENCE; blank account |
| NDS-INV-26042 | Northstar Data Systems, Inc. | 10/03/2026 | USD | 4,900.00 | 324.00 | No mismatch in seven checked fields; uncalibrated local draft | NOT_FOUND; blank account |
| VCA/26-27/0187 | Vertex Cloud Analytics Pvt. Ltd. | 10/05/2026 | INR | 276,000.00 | 42,516.00 | Invoice number differs from reference `VCA-26-27-0187`; uncalibrated local draft | NOT_FOUND; blank account |
| HP-2026-774 | HarborPoint Consulting Group | 10/07/2026 | CAD | 6,540.00 | 1,033.80 | No mismatch in seven checked fields; uncalibrated local draft | NOT_FOUND; blank account |
| SOS-INV-26155 | Summit Office Supplies Co. | 10/09/2026 | INR | 78,900.00 | 10,314.00 | No mismatch in seven checked fields; uncalibrated local draft | NOT_FOUND; blank account |
| GDM-260913 | Greenline Digital Media LLC | Blank | USD | 8,000.00 | 0.00 | Required invoice date missing; reference says 10/10/2026; uncalibrated local draft | NOT_FOUND; blank account |
| EMS-2026-0918 | EuroMatrix Software GmbH | 10/12/2026 | EUR | 10,075.00 | 1,476.25 | No mismatch in seven checked fields; uncalibrated local draft | NOT_FOUND; blank account |
| PLF-SG-261024 | Pacific Logistics & Freight | Blank | SGD | 3,575.00 | 0.00 | Required invoice date missing; reference says 10/14/2026; uncalibrated local draft | NOT_FOUND; blank account |
| CPS-2026-1048 | CedarPeak Security Services | 10/16/2026 | USD | 9,850.00 | 787.50 | No mismatch in seven checked fields; uncalibrated local draft | NOT_FOUND; blank account |
| BRE-INV-2026-311 | BlueRiver Engineering Ltd. | 10/18/2026 | GBP | 6,690.00 | 1,151.20 | No mismatch in seven checked fields; uncalibrated local draft | NOT_FOUND; blank account |

## Final disposition

The application runs and exports the required columns, but this test does **not** support calling these 10 invoices fully validated or auto-approved. Review the two missing dates and the invoice-number punctuation difference against the source. Provide a reliable MDM region/account mapping for these vendors, or accept blank Billing Accounts. For the two supplied `.msg` files, save the original Outlook emails again as complete Outlook Message Format files before retrying.
