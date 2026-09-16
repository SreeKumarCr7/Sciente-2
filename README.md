# Financial statement extractor

## Problem

Extract 23 income statement, balance sheet, and cash flow fields from up to two financial statement PDFs with traceable evidence.

## Architecture

`PDF -> pdfplumber tables -> aliases and rules -> validation/confidence -> Docling OCR only when needed -> LLM fallback for unresolved fields -> result`

pdfplumber is the primary extraction engine. Docling is loaded lazily only when pdfplumber finds no usable financial tables, for scanned/image-based PDFs. Deterministic extraction runs first; Gemini is called only for fields that cannot be confidently found. Results are printed in the terminal as JSON by default, or as a table with `--table`.

## Approaches evaluated

1. **pdfplumber + rules:** primary lightweight extraction for text-oriented financial PDFs, with page-preserving table extraction.
2. **Docling OCR fallback:** used only for scanned or visually complex statements when pdfplumber cannot find usable financial tables.

## Fallback, validation, and output

Aliases, normalized labels, nearby numeric values, year/column detection, units, and negative-number parsing are the deterministic checks. A fallback must receive only relevant content, return `not found` when unsupported, preserve year/unit, and include evidence. It must never guess. Each result contains `field`, `value`, `year`, `unit`, `source`, `confidence`, and `evidence`.

Sources are `deterministic`, `llm_fallback`, or `not_found`; API failures remain unresolved and are listed in `errors`. LLM logs include model, input/output tokens, input/output cost, and total cost. Pricing is configured per provider/model; no fake pricing is hard-coded.

## Assumptions

- PDFs contain selectable text and tables that pdfplumber can detect.
- The relevant reporting year and units are present in the document.
- Missing fields are reported rather than inferred.

## Cross-Checked Results

The following records preserve the extracted values separately for each assessment PDF. Amounts are reported in the document's own units.

### 2022-annual.pdf

Reporting period: year ended December 31, 2022. Unit: USD millions unless stated otherwise.

| # | Field | Cross-checked result | Status |
|---:|---|---:|---|
| 1 | Net Revenue / Sales | $3,374.9M | Explicit |
| 2 | COGS | $2,035.1M | Explicit, Cost of sales |
| 3 | SG&A Expense | $797.5M | Explicit |
| 4 | Depreciation & Amortisation | $118.9M | Explicit, cash flow statement |
| 5 | Operating Income (EBIT) | $369.5M | Explicit, Operating profit |
| 6 | Interest Expense | $(52.2)M expense | Explicit |
| 7 | Net Income | $401.1M | Explicit, attributable to common shareholders |
| 8 | Total Current Assets | $1,751.9M | Explicit |
| 9 | Trade Receivables (Net) | $474.7M | Explicit |
| 10 | Inventory | $439.8M | Explicit |
| 11 | Net PP&E | $509.9M | Explicit |
| 12 | Total Assets | $4,390.2M | Explicit |
| 13 | Total Current Liabilities | $1,488.2M | Explicit |
| 14 | Long-Term Debt | $543.7M | Explicit |
| 15 | Total Liabilities | $2,486.2M | Derived; not a single reported line |
| 16 | Retained Earnings | $2,822.8M | Explicit |
| 17 | Total Shareholders' Equity | $1,901.4M | Explicit; total equity is $1,904.0M |
| 18 | Shares Outstanding | 56,325,382 shares | Explicit |
| 19 | CF From Operations | $(151.6)M | Explicit, used for operating activities |
| 20 | CF From Investing | $264.0M | Explicit, provided by investing activities |
| 21 | CF From Financing | $106.0M | Explicit, provided by financing activities |
| 22 | Net Change in Cash | $179.0M | Explicit; excludes $(39.4)M FX effect |
| 23 | Cash & Equivalents (End of Period) | $657.6M | Explicit |

Cross-check pages: income statement pages 33 and 57; balance sheet page 59; cash flow statement pages 60-61.

### icici-bank-2026-financial-statements.pdf

Reporting period: year ended March 31, 2026. Unit: INR thousands unless stated otherwise. This is a bank financial statement, so corporate fields are mapped only where a defensible banking equivalent exists.

| # | Field | Cross-checked result | Status |
|---:|---|---:|---|
| 1 | Net Revenue / Sales | INR 2,007,036,834 | Banking equivalent: Total income |
| 2 | COGS | Not applicable; closest equivalent INR 818,708,581 | Banking equivalent: Interest expended |
| 3 | SG&A Expense | INR 472,339,479 | Banking equivalent: Operating expenses |
| 4 | Depreciation & Amortisation | INR 25,407,805 | Explicit, cash flow statement |
| 5 | Operating Income (EBIT) | INR 715,988,774 | Banking definition: Operating profit |
| 6 | Interest Expense | INR 818,708,581 | Banking equivalent: Interest expended |
| 7 | Net Income | INR 501,466,407 | Explicit |
| 8 | Total Current Assets | Not presented; closest liquidity subtotal INR 2,303,351,621 | Banking format |
| 9 | Trade Receivables (Net) | Not applicable; advances INR 15,538,929,484 | Banking equivalent |
| 10 | Inventory | Not applicable | Banking format |
| 11 | Net PP&E | INR 139,224,715 | Banking equivalent: Fixed assets, net |
| 12 | Total Assets | INR 23,725,309,971 | Explicit |
| 13 | Total Current Liabilities | Not presented | Banking format |
| 14 | Long-Term Debt | INR 1,249,941,129 | Banking equivalent: Borrowings |
| 15 | Total Liabilities | INR 20,351,595,791 | Derived; not a single reported line |
| 16 | Retained Earnings | INR 1,285,442,549 | Reported within reserves and surplus |
| 17 | Total Shareholders' Equity | INR 3,373,714,180 | Capital, ESOP outstanding, and reserves/surplus |
| 18 | Shares Outstanding | 7,160,112,569 shares | Explicit |
| 19 | CF From Operations | INR 647,256,048 | Explicit |
| 20 | CF From Investing | INR (163,278,572) | Explicit |
| 21 | CF From Financing | INR (45,726,342) | Explicit |
| 22 | Net Change in Cash | INR 447,731,658 | Includes INR 9,480,524 FX effect |
| 23 | Cash & Equivalents (End of Period) | INR 2,303,351,621 | Banking equivalent |

For the ICICI document, `not applicable` and derived values must not be fabricated by deterministic extraction. They should remain explicitly labelled in the final result, with the source and evidence retained.

## Setup and run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python app.py 2022-annual.pdf
python app.py 2022-annual.pdf icici-bank-2026-financial-statements.pdf --table
```

## Coding-Test Output

Use `--table` for one or two PDFs. Each document prints all 23 required fields with `field`, `value`, `year`, `unit`, `source`, `page`, `confidence`, and `status`, followed by an extraction summary and LLM cost report. When two PDFs are supplied, an overall summary is printed after both document reports.

```text
FINANCIAL STATEMENT EXTRACTION
Document: 2022-annual.pdf
| # | Field | Value | Year | Unit | Source | Page | Confidence | Status |
| 1 | Net Revenue / Sales | 3374.9 | 2022 | USD million | deterministic | 45 | 0.98 | Found |
...
| 23 | Cash & Equivalents (End of Period) | 657.6 | 2022 | USD million | deterministic | 61 | 0.98 | Found |

EXTRACTION SUMMARY
Total fields: 23
Deterministic: X
LLM fallback: X
Not found: X
```

pdfplumber is always attempted first. Deterministic rules use only extracted table/context rows and preserve explicit year/value relationships, parentheses, negative values, units, evidence, and pages. If a field remains unresolved, Gemini receives only relevant extracted context for that field. Gemini must return `found` with supporting context; otherwise the result is `Not Found`. LLM cost is calculated from reported input/output tokens multiplied by the configured per-million-token prices. No values, pages, tokens, costs, or confidence scores are fabricated.

## Structure

```text
financial_statement_extractor/
├── app.py
├── extractor.py
├── llm.py
├── requirements.txt
├── README.md
├── .env.example
└── .gitignore
```