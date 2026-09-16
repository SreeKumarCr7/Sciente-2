"""pdfplumber extraction and deterministic financial field extraction."""

import io
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
import time

import pdfplumber

from llm import empty_cost_log, llm_fallback


FIELDS = [
    ("Net Revenue / Sales", [
        "net revenue", "net sales", "total income", "total revenue", "revenue", "sales",
    ]),
    ("COGS", [
        "cost of goods sold", "cost of sales", "cost of revenue", "interest expended", "cogs",
    ]),
    ("SG&A Expense", [
        "selling, general and administrative", "selling general and administrative",
        "operating expenses", "sg&a", "sga", "selling and administrative",
    ]),
    ("Depreciation & Amortisation", [
        "depreciation and amortization", "depreciation and amortisation",
        "depreciation & amortization", "depreciation & amortisation",
    ]),
    ("Operating Income (EBIT)", [
        "operating income", "operating profit", "income from operations", "ebit",
    ]),
    ("Interest Expense", ["interest expense", "interest expended", "interest costs", "finance costs"]),
    ("Net Income", ["net income", "net profit", "net profit after tax", "profit after tax", "profit for the year"]),
    ("Total Current Assets", ["total current assets"]),
    ("Trade Receivables (Net)", ["trade receivables", "accounts receivable", "receivables"]),
    ("Inventory", ["inventory", "inventories"]),
    ("Net PP&E", [
        "property, plant and equipment", "property plant and equipment", "fixed assets", "net ppe", "net pp&e",
    ]),
    ("Total Assets", ["total assets"]),
    ("Total Current Liabilities", ["total current liabilities"]),
    ("Long-Term Debt", ["long-term debt", "long term debt", "non-current debt", "borrowings"]),
    ("Total Liabilities", ["total liabilities"]),
    ("Retained Earnings", ["retained earnings", "earnings"]),
    ("Total Shareholders' Equity", ["total shareholders' equity", "total stockholders' equity", "shareholders equity"]),
    ("Shares Outstanding", ["shares outstanding", "ordinary shares outstanding", "equity shares"]),
    ("CF From Operations", [
        "cash flow from operating activities", "provided by operating activities",
        "total provided by operating activities", "total used for operating activities",
        "cash from operations", "cash generated from operations",
    ]),
    ("CF From Investing", [
        "cash flow from investing activities", "provided by investing activities",
        "total provided by investing activities", "total used for investing activities",
        "cash from investing", "cash used in investing",
    ]),
    ("CF From Financing", [
        "cash flow from financing activities", "provided by financing activities",
        "total provided by financing activities", "total used for financing activities",
        "cash from financing", "cash used in financing",
    ]),
    ("Net Change in Cash", [
        "net change in cash", "increase decrease in cash", "increase in cash and cash equivalents",
        "net increase in cash",
    ]),
    ("Cash & Equivalents (End of Period)", [
        "cash and cash equivalents at end", "cash and cash equivalents", "cash & equivalents",
        "cash equivalents at end",
    ]),
]

NUMBER_PATTERN = re.compile(
    r"(?<![\w])(?:[$€£₹]\s*)?(?:\(\s*-?\s*\d[\d,]*(?:\.\d+)?\s*\)|-?\s*\d[\d,]*(?:\.\d+)?)(?![\w])"
)
YEAR_PATTERN = re.compile(r"\b(?:19|20)\d{2}\b")
SECTION_PATTERN = re.compile(
    r"\b(?:income statement|statement of income|statement of operations|"
    r"profit and loss|p&l|balance sheet|statement of financial position|"
    r"cash flow statement|statement of cash flows)\b",
    re.IGNORECASE,
)
UNIT_PATTERN = re.compile(
    r"\b(?:USD|EUR|GBP|INR|CAD|AUD|JPY|CNY)\b"
    r"(?:\s+(?:in|,)?\s*(?:thousands?|millions?|billions?|crores?|lakhs?))?"
    r"|[$€£₹]\s*(?:in\s+)?(?:thousands?|millions?|billions?|crores?|lakhs?)?"
    r"|\b(?:in\s+)?(?:thousands?|millions?|billions?|crores?|lakhs?)\b",
    re.IGNORECASE,
)


def normalize_label(value: str) -> str:
    """Normalize labels while retaining word boundaries for row matching."""
    normalized = value.lower().replace("&", " and ")
    normalized = re.sub(r"[’'`\-_/]+", " ", normalized)
    return re.sub(r"[^a-z0-9]+", " ", normalized).strip()


def _alias_matches(line: str, alias: str) -> bool:
    normalized_line = normalize_label(line)
    normalized_alias = normalize_label(alias)
    return bool(re.search(rf"(?<!\w){re.escape(normalized_alias)}(?!\w)", normalized_line))


def _row_matches_alias(row: list[str], aliases: list[str]) -> bool:
    """Match aliases near the start of label cells, not embedded page prose."""
    normalized_aliases = [normalize_label(alias) for alias in aliases]
    for cell in row[:2]:
        normalized_cell = normalize_label(cell)
        if re.search(
            r"\b(?:margin|ratio|growth|yield|turnover|per employee\d*|"
            r"per share\d*|to working funds\d*|capitalization)\b",
            normalized_cell,
        ):
            continue
        for normalized_alias in normalized_aliases:
            if normalized_cell.startswith(normalized_alias) and (
                len(normalized_cell) == len(normalized_alias)
                or not normalized_cell[len(normalized_alias)].isalnum()
            ):
                return True
    return False


def _parse_number(raw_value: str) -> str:
    """Return a plain numeric string, converting accounting parentheses to minus."""
    value = raw_value.strip().replace(",", "").replace(" ", "")
    negative = value.startswith("(") and value.endswith(")")
    value = value.strip("($€£₹)")
    if negative and not value.startswith("-"):
        value = f"-{value}"
    return value


def _years_from_lines(lines: list[str]) -> list[str]:
    years = []
    for line in lines:
        for year in YEAR_PATTERN.findall(line):
            if year not in years:
                years.append(year)
    return years


def _unit_from_lines(lines: list[str]) -> str | None:
    for line in lines:
        match = UNIT_PATTERN.search(line)
        if match:
            return re.sub(r"\s+", " ", match.group(0)).strip(" ,")
    return None


def _normalized_unit(lines: list[str]) -> str | None:
    text = " ".join(lines)
    unit = _unit_from_lines(lines)
    if not unit:
        return None
    currency = None
    if "₹" in text or re.search(r"\bINR\b", text, re.IGNORECASE):
        currency = "INR"
    elif "$" in text or re.search(r"\bUSD\b", text, re.IGNORECASE):
        currency = "USD"
    scale = None
    for candidate in ("billion", "million", "thousand", "crore", "lakh"):
        if candidate in unit.lower():
            scale = candidate
            break
    return " ".join(part for part in (currency, scale) if part) or unit


def _public_value(value: object) -> object:
    if value in (None, "not_found", "Not Found", "not_applicable"):
        return "Not Found"
    try:
        number = float(str(value))
        return int(number) if number.is_integer() else number
    except (TypeError, ValueError):
        return value


def _empty_result(field: str) -> dict[str, object]:
    return {
        "field": field,
        "value": None,
        "year": None,
        "unit": None,
        "source": "needs_llm",
        "confidence": 0.0,
        "evidence": None,
        "page": None,
        "status": "not_found",
    }


def _table_cells(line: str) -> list[str] | None:
    """Return Markdown table cells, or None for ordinary text."""
    if "|" not in line:
        return None
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return cells if len(cells) > 1 else None


def _table_year_value(rows: list[list[str]], row_index: int) -> tuple[str | None, str] | None:
    """Map the latest year header to the value in the same table column."""
    row_cells = rows[row_index]
    for header_index in range(row_index - 1, -1, -1):
        header_years = [year for cell in rows[header_index] for year in YEAR_PATTERN.findall(cell)]
        year_columns = {
            index: year
            for index, cell in enumerate(rows[header_index])
            for year in YEAR_PATTERN.findall(cell)
        }
        if not year_columns:
            continue
        if len(year_columns) == 1:
            numbers = [number for cell in row_cells for number in NUMBER_PATTERN.findall(cell)]
            if numbers:
                value = numbers[0] if len(header_years) > 1 else numbers[-1]
                return header_years[0], _parse_number(value)
        value_columns = []
        for index, year in year_columns.items():
            if index >= len(row_cells):
                continue
            values = NUMBER_PATTERN.findall(row_cells[index])
            if len(values) == 1:
                value_columns.append((year, _parse_number(values[0])))
        if len(value_columns) == len(year_columns):
            return max(value_columns, key=lambda item: item[0])
    return None


def _has_multiple_year_header(rows: list[list[str]]) -> bool:
    return any(
        len({year for cell in row for year in YEAR_PATTERN.findall(cell)}) >= 2
        for row in rows
    )


def _extract_table_value(rows: list[list[str]], aliases: list[str]) -> dict[str, object] | None:
    """Find a field row and map its value to the latest explicit year."""
    aliases = sorted(aliases, key=len, reverse=True)
    matching_indexes = [
        index for index, row in enumerate(rows)
        if _row_matches_alias(row, aliases)
    ]
    if not matching_indexes:
        return None

    for matching_index in matching_indexes:
        table_value = _table_year_value(rows, matching_index)
        if table_value:
            year, value = table_value
            context_rows = rows[max(0, matching_index - 2):matching_index + 2]
            context_lines = [" | ".join(row) for row in context_rows]
            unit = _normalized_unit(context_lines)
            return {
                "value": value,
                "year": year,
                "unit": unit,
                "confidence": min(0.92 + (0.05 if unit else 0.0), 0.99),
                "evidence": " ".join(context_lines)[:500],
            }

    if _has_multiple_year_header(rows):
        return None

    matching_index = matching_indexes[0]
    row = rows[matching_index]
    numbers = [number for cell in row for number in NUMBER_PATTERN.findall(cell)]
    if len(numbers) != 1:
        return None
    context_lines = [" | ".join(row)]
    return {
        "value": _parse_number(numbers[0]),
        "year": None,
        "unit": _normalized_unit(context_lines),
        "confidence": 0.78,
        "evidence": context_lines[0][:500],
    }


def deterministic_extract(tables: list[dict[str, object]] | str) -> list[dict[str, object]]:
    """Extract each requested field from pdfplumber table rows."""
    if isinstance(tables, str):
        tables = [{"page": None, "rows": [[tables]], "text": tables}]

    results = [_empty_result(field) for field, _ in FIELDS]
    for result, (field, aliases) in zip(results, FIELDS):
        for table in tables:
            match = _extract_table_value(table["rows"], aliases)
            if not match:
                continue
            result.update(match)
            result["source"] = "deterministic"
            result["page"] = table.get("page")
            result["status"] = "found"
            break
    return results


def _all_rows(tables: list[dict[str, object]]) -> list[tuple[int | None, list[str]]]:
    return [
        (table.get("page"), row)
        for table in tables
        for row in table.get("rows", [])
    ]


def _bank_row_value(
    tables: list[dict[str, object]], aliases: list[str], prefer_first: bool = False
) -> dict[str, object] | None:
    years = [
        year
        for _, row in _all_rows(tables)
        for cell in row
        for year in YEAR_PATTERN.findall(cell)
    ]
    latest_year = max(years) if years else None
    for page, row in _all_rows(tables):
        if not _row_matches_alias(row, aliases):
            continue
        numbers = [number for cell in row for number in NUMBER_PATTERN.findall(cell)]
        if not numbers:
            continue
        value = numbers[0] if prefer_first else numbers[-1]
        return {
            "value": _parse_number(value),
            "year": latest_year,
            "unit": _normalized_unit([" | ".join(row)]),
            "confidence": 0.9,
            "evidence": " | ".join(row)[:500],
            "page": page,
        }
    return None


def _apply_icici_semantics(results: list[dict[str, object]], tables: list[dict[str, object]]) -> None:
    """Map corporate fields to explicit banking equivalents without inventing values."""
    by_field = {result["field"]: result for result in results}

    equivalent_rows = {
        "Trade Receivables (Net)": ["advances"],
        "Net PP&E": ["fixed assets"],
        "Long-Term Debt": ["borrowings"],
        "Total Shareholders' Equity": ["total shareholders funds", "total equity"],
        "Shares Outstanding": ["equity shares"],
    }
    for field, aliases in equivalent_rows.items():
        result = by_field[field]
        if result["source"] == "needs_llm":
            match = _bank_row_value(tables, aliases)
            if match:
                result.update(match)
                result["source"] = "deterministic"
                result["status"] = "found"

    for field in ("Inventory", "Total Current Liabilities"):
        result = by_field[field]
        result.update({
            "value": "Not Found",
            "source": "not_found",
            "confidence": 0.95,
            "evidence": "Banking-format statement does not present this corporate subtotal.",
            "status": "not_found",
        })

    total_assets = _bank_row_value(tables, ["total assets"])
    total_equity = _bank_row_value(tables, ["total equity", "total shareholders funds"])
    result = by_field["Total Liabilities"]
    # Do not derive total liabilities; the assessment requires reported values only.


def _finalize_results(results: list[dict[str, object]]) -> None:
    for result in results:
        result["value"] = _public_value(result.get("value"))
        if result.get("year"):
            try:
                result["year"] = int(str(result["year"]))
            except (TypeError, ValueError):
                pass
        if result["source"] == "deterministic":
            result["status"] = "found"
        elif result["source"] in {"llm_fallback", "llm"}:
            result["source"] = "llm"
            result["status"] = "found" if result["value"] != "Not Found" else "not_found"
        else:
            result["source"] = "not_found"
            result["status"] = "not_found"
            result["confidence"] = 0.0


def _relevant_context(tables: list[dict[str, object]], field: str) -> str:
    """Return only relevant table rows for one unresolved field."""
    aliases = dict(FIELDS)[field]
    snippets = []
    for table in tables:
        table_text = str(table.get("text", ""))
        if any(_alias_matches(table_text, alias) for alias in aliases):
            snippets.append(f"Page {table.get('page')}:\n{table_text}")
            continue
        lines = str(table.get("page_text", "")).splitlines()
        for index, line in enumerate(lines):
            if any(_alias_matches(line, alias) for alias in aliases):
                context = lines[max(0, index - 4):index + 4]
                snippets.append(f"Page {table.get('page')}:\n" + "\n".join(context))
                break
    return "\n\n".join(snippets)[:8000]


def _add_cost(total: dict[str, object], call: dict[str, object]) -> None:
    for key in ("input_tokens", "output_tokens", "input_cost", "output_cost", "total_cost"):
        total[key] += call[key]
    total["fallback_calls"] += call["fallback_calls"]
    total["model"] = call["model"]


def _clean_rows(raw_rows: list[list[object]]) -> list[list[str]]:
    return [[str(cell or "").strip() for cell in row] for row in raw_rows]


def _extract_with_docling_fallback(
    pdf_bytes: bytes, filename: str
) -> tuple[str, list[dict[str, object]], dict[str, object], list[dict[str, object]]]:
    """Use Docling only when pdfplumber cannot find usable financial tables."""
    from docling.document_converter import DocumentConverter
    from docling_core.types.doc import DocItemLabel

    temporary_path = None
    try:
        with NamedTemporaryFile(suffix=".pdf", delete=False) as temporary_file:
            temporary_file.write(pdf_bytes)
            temporary_path = Path(temporary_file.name)

        document = DocumentConverter().convert(str(temporary_path)).document
        number_of_pages = document.num_pages() if callable(document.num_pages) else document.num_pages
        tables = []
        pages_with_tables = set()
        for item, _ in document.iterate_items():
            if item.label != DocItemLabel.TABLE:
                continue
            rows = [[str(cell.text or "").strip() for cell in row] for row in item.data.grid]
            if not any(cell for row in rows for cell in row):
                continue
            page_numbers = [
                provenance.page_no for provenance in item.prov
                if provenance.page_no is not None
            ]
            page = page_numbers[0] if page_numbers else None
            if page is not None:
                pages_with_tables.add(page)
            tables.append({
                "page": page,
                "rows": rows,
                "columns": max((len(row) for row in rows), default=0),
                "text": "\n".join(" | ".join(row) for row in rows).strip(),
                "page_text": "",
                "relevant": True,
            })
        if not tables:
            raise ValueError("Docling OCR fallback returned no tables.")
        return "\n\n".join(table["text"] for table in tables), tables, {
            "number_of_pages": int(number_of_pages or 0),
            "total_tables": len(tables),
            "pages_with_tables": sorted(pages_with_tables),
            "relevant_tables": len(tables),
            "extraction_method": "docling_ocr_fallback",
        }, tables
    except Exception as error:
        raise RuntimeError(f"Docling OCR fallback failed for {filename}: {error}") from error
    finally:
        if temporary_path:
            temporary_path.unlink(missing_ok=True)


def _extract_pdf(
    pdf_bytes: bytes, filename: str
) -> tuple[str, list[dict[str, object]], dict[str, object], list[dict[str, object]]]:
    """Extract all non-empty tables and retain relevant financial tables."""
    if not pdf_bytes or not filename.lower().endswith(".pdf"):
        raise ValueError("A non-empty PDF file is required.")

    tables = []
    pages_with_tables = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        number_of_pages = len(pdf.pages)
        for page_number, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text() or ""
            page_tables = page.extract_tables() or []
            if page_tables:
                pages_with_tables.append(page_number)
            for raw_rows in page_tables:
                rows = _clean_rows(raw_rows)
                if not any(cell for row in rows for cell in row):
                    continue
                table_text = "\n".join(" | ".join(row) for row in rows).strip()
                relevant = any(
                    _row_matches_alias(row, aliases)
                    for row in rows
                    for _, aliases in FIELDS
                ) or bool(SECTION_PATTERN.search(page_text) and len(rows) > 1)
                tables.append({
                    "page": page_number,
                    "rows": rows,
                    "columns": max((len(row) for row in rows), default=0),
                    "text": table_text,
                    "page_text": page_text,
                    "relevant": relevant,
                })

    relevant_tables = [table for table in tables if table["relevant"]]
    if not relevant_tables:
        return _extract_with_docling_fallback(pdf_bytes, filename)
    text = "\n\n".join(table["text"] for table in relevant_tables).strip()
    if not text:
        raise ValueError("pdfplumber returned no relevant financial tables.")
    stats = {
        "number_of_pages": number_of_pages,
        "total_tables": len(tables),
        "pages_with_tables": pages_with_tables,
        "relevant_tables": len(relevant_tables),
        "extraction_method": "pdfplumber",
    }
    return text, relevant_tables, stats, tables


def extract_financial_statement(pdf_bytes: bytes, filename: str) -> dict[str, object]:
    """Run extraction and return the complete 23-field report."""
    started_at = time.perf_counter()
    text, tables, stats, all_tables = _extract_pdf(pdf_bytes, filename)
    results = deterministic_extract(tables)
    if "icici" in filename.lower():
        _apply_icici_semantics(results, all_tables)

    cost = empty_cost_log()
    errors = []
    for result in results:
        if result["source"] != "needs_llm":
            continue
        try:
            fallback, call_cost = llm_fallback(
                str(result["field"]), _relevant_context(tables, str(result["field"]))
            )
            _add_cost(cost, call_cost)
            if fallback["status"] == "found":
                result.update(fallback)
                result["source"] = "llm"
                result["confidence"] = 0.7
                result["status"] = "found"
            else:
                result.update({
                    "value": "Not Found",
                    "year": fallback.get("year"),
                    "unit": fallback.get("unit"),
                    "evidence": fallback.get("evidence"),
                    "page": fallback.get("page"),
                    "source": "not_found",
                    "status": "not_found",
                })
        except Exception as error:
            errors.append(f"{result['field']}: {error}")
            result.update({
                "value": "Not Found",
                "source": "not_found",
                "status": "not_found",
            })

    _finalize_results(results)
    deterministic_count = sum(result["source"] == "deterministic" for result in results)
    llm_count = sum(result["source"] == "llm" for result in results)
    not_found_count = sum(result["source"] == "not_found" for result in results)
    print(
        f"document={filename} pages={stats['number_of_pages']} "
        f"tables={stats['total_tables']} relevant_tables={stats['relevant_tables']} "
        f"deterministic={deterministic_count} llm={llm_count} not_found={not_found_count}"
    )
    return {
        "filename": filename,
        **stats,
        "extraction_method": stats.get("extraction_method", "pdfplumber"),
        "results": results,
        "text": text,
        "cost": cost,
        "errors": errors,
        "tables": all_tables,
        "representative_tables": all_tables[:5],
        "processing_seconds": round(time.perf_counter() - started_at, 3),
    }