"""Command-line entry point for financial statement extraction."""

import argparse
import json
from pathlib import Path

from extractor import extract_financial_statement


def _print_table(document: dict[str, object]) -> None:
    """Print the coding-test report without requiring a table dependency."""
    results = document["results"]
    deterministic = sum(result["source"] == "deterministic" for result in results)
    llm_count = sum(result["source"] == "llm" for result in results)
    not_found = sum(result["source"] == "not_found" for result in results)
    print("\nFINANCIAL STATEMENT EXTRACTION")
    print(f"Document: {document['filename']}")
    print()
    print("| # | Field | Value | Year | Unit | Source | Page | Confidence | Status |")
    print("|---:|---|---:|---:|---|---|---:|---:|---|")
    for index, result in enumerate(results, start=1):
        year = result["year"] if result["year"] is not None else "-"
        page = result["page"] if result["page"] is not None else "-"
        confidence = f"{result['confidence']:.2f}" if result["source"] != "not_found" else "-"
        status = "Found" if result["status"] == "found" else "Not Found"
        print(
            f"| {index} | {result['field']} | {result['value']} | {year} | "
            f"{result['unit'] or '-'} | {result['source']} | {page} | {confidence} | {status} |"
        )
    print()
    print("EXTRACTION SUMMARY")
    print("------------------")
    print(f"Total fields: {len(results)}")
    print(f"Deterministic: {deterministic}")
    print(f"LLM fallback: {llm_count}")
    print(f"Not found: {not_found}")
    cost = document["cost"]
    print("\nLLM COST REPORT")
    print("---------------")
    print(f"Model: {cost['model']}")
    print(f"LLM calls: {cost['fallback_calls']}")
    print(f"Input tokens: {cost['input_tokens']}")
    print(f"Output tokens: {cost['output_tokens']}")
    print(f"Input cost: ${cost['input_cost']:.6f}")
    print(f"Output cost: ${cost['output_cost']:.6f}")
    print(f"Total LLM cost: ${cost['total_cost']:.6f}")
    print("\nESTIMATED COST FOR 1,000 DOCUMENTS")
    print("----------------------------------")
    print(f"Estimated total cost: ${float(cost['total_cost']) * 1000:.6f}")
    print(f"Processing time: {document['processing_seconds']} seconds")
    if document.get("errors"):
        print("Errors:")
        for error in document["errors"]:
            print(f"- {error}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract financial fields from PDF files.")
    parser.add_argument("pdf", nargs="+", type=Path, help="One or more PDF files")
    parser.add_argument("--table", action="store_true", help="Print a readable table instead of JSON")
    args = parser.parse_args()

    documents = []
    for index, pdf_path in enumerate(args.pdf):
        if not pdf_path.is_file():
            parser.error(f"PDF does not exist: {pdf_path}")
        try:
            document = extract_financial_statement(pdf_path.read_bytes(), pdf_path.name)
            documents.append(document)
        except Exception as error:
            print(json.dumps({"filename": pdf_path.name, "error": str(error)}, indent=2))
            continue

        if index:
            print()
        if args.table:
            _print_table(document)
        else:
            print(json.dumps(document, indent=2, default=str))

    if args.table and len(documents) > 1:
        results = [result for document in documents for result in document["results"]]
        print("\nOVERALL SUMMARY")
        print("---------------")
        print(f"Documents processed: {len(documents)}")
        print(f"Total fields processed: {len(results)}")
        print(f"Deterministic extractions: {sum(r['source'] == 'deterministic' for r in results)}")
        print(f"LLM fallbacks: {sum(r['source'] == 'llm' for r in results)}")
        print(f"Not found: {sum(r['source'] == 'not_found' for r in results)}")
        print(f"Total LLM cost: ${sum(float(d['cost']['total_cost']) for d in documents):.6f}")


if __name__ == "__main__":
    main()