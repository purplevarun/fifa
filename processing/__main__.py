import argparse
import json
import shutil
import sys
from pathlib import Path

from .catalog import coverage_report, inventory, status, validate_records
from .store import Store, json_text
from .pipeline import (
    approve_review,
    backup_records,
    dashboard_data,
    extract_pending,
    import_pending,
    make_review,
    parse_sequences,
    record_processing_run,
    write_json,
)
from .reconciliation import reconcile_totals


def process(root):
    data_directory = root / "processing" / "data"
    output = root / "frontend" / "public" / "data" / "dashboard.json"
    if data_directory.is_symlink() or data_directory.parent.is_symlink():
        raise ValueError("Refusing to delete a symlinked processing data directory")
    if data_directory.exists() and not data_directory.is_dir():
        raise ValueError(f"Expected a processing data directory: {data_directory}")
    print(
        f"Full rebuild: replacing {data_directory}. The published dashboard is kept until validation succeeds.",
        flush=True,
    )
    if data_directory.exists():
        shutil.rmtree(data_directory)
    data_directory.mkdir(parents=True, exist_ok=True)
    (root / "raw_screenshots").mkdir(exist_ok=True)
    store = Store()
    manifest = inventory(store, root)
    extraction = extract_pending(
        store, root, progress=lambda message: print(message, flush=True)
    )
    source_ids = extraction.pop("processed_source_ids")
    imported = import_pending(store, refreshed_source_ids=source_ids)
    errors = validate_records(store)
    errors.extend(
        f"Extracted statistics could not be imported: {source['path']}: {source['reason']}"
        for source in imported["skipped_sources"]
    )
    failed = bool(extraction["errors"] or errors)
    run = record_processing_run(store, "clean", extraction, imported)
    if failed:
        run["status"] = "partial"
        store.update("processing_runs", run["id"], {"status": "partial"})
    result = {
        "output": str(output),
        "diagnostics": str(data_directory / "diagnostics.json"),
        "inventory": manifest,
        "extraction": extraction,
        "import": imported,
        "validation_errors": errors,
        "processing_run": run,
        "message": "Processing is incomplete. The previous dashboard.json was not replaced."
        if failed
        else "dashboard.json rebuilt directly from screenshots. The local dashboard updates automatically.",
    }
    write_json(data_directory / "processing-report.json", result)
    store.save(data_directory / "diagnostics.json")
    if not failed:
        write_json(output, dashboard_data(store))
    print(json_text(result), end="")
    return int(failed)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Transform FIFA screenshots directly into dashboard.json."
    )
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parent.parent
    )
    parser.add_argument(
        "--diagnostics",
        type=Path,
        help="JSON evidence for maintenance commands; defaults to ROOT/processing/data/diagnostics.json",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("data", help="Read the published dashboard.json")
    commands.add_parser("inventory", help="Inventory images without running OCR")
    commands.add_parser(
        "status", help="Show canonical record counts and outstanding source states"
    )
    commands.add_parser(
        "validate", help="Validate relationships and published JSON consistency"
    )
    reporter = commands.add_parser(
        "report",
        help="Report fixture, player and team-stat coverage with reconciliation warnings",
    )
    reporter.add_argument("--club", default="Notts County")
    reporter.add_argument(
        "--output",
        type=Path,
        help="Write the full report as JSON and print its summary",
    )
    reconciliation = commands.add_parser(
        "reconcile",
        help="Compare captured cumulative player stats with reviewed match records",
    )
    reconciliation.add_argument("--season")
    reconciliation.add_argument("--club", default="Notts County")
    reconciliation.add_argument(
        "--rating-decimals", type=int, choices=(1, 2), default=1
    )
    reconciliation.add_argument("--output", type=Path)
    commands.add_parser(
        "process",
        help="Rebuild all screenshots and atomically publish dashboard.json; accepts no options",
    )
    reviewer = commands.add_parser(
        "review",
        help="Write an editable review document; never overwrites an existing file",
    )
    reviewer.add_argument("--screenshots", help="Optional numeric screenshot selection")
    reviewer.add_argument(
        "--match",
        help="Propose an approved match UUID for the selected performance records",
    )
    reviewer.add_argument("--output", type=Path, required=True)
    approver = commands.add_parser(
        "approve",
        help="Validate and transactionally import a visually checked review document",
    )
    approver.add_argument("review_file", type=Path)
    approver.add_argument(
        "--note", required=True, help="Describe the source checks and any corrections"
    )
    approver.add_argument(
        "--replace-reviewed",
        action="store_true",
        help="Explicitly allow corrections to existing non-null values",
    )
    exporter = commands.add_parser(
        "export", help="Regenerate the read-only JSON dataset for React"
    )
    exporter.add_argument("--output", type=Path)
    backup = commands.add_parser(
        "backup", help="Back up JSON processing diagnostics, including review history"
    )
    backup.add_argument("destination", type=Path)
    arguments = parser.parse_args(argv)
    root = arguments.root.resolve()
    data_directory = root / "processing" / "data"
    output = root / "frontend" / "public" / "data" / "dashboard.json"
    diagnostics = arguments.diagnostics or data_directory / "diagnostics.json"
    if arguments.command == "process":
        if arguments.diagnostics is not None:
            parser.error(
                "process rebuilds from screenshots; --diagnostics is not supported"
            )
        return process(root)
    if arguments.command == "data":
        if not output.is_file():
            raise ValueError("No dashboard.json yet. Run ./run process first.")
        print(json_text(json.loads(output.read_text(encoding="utf-8"))), end="")
        return 0
    if arguments.command == "inventory":
        (root / "raw_screenshots").mkdir(parents=True, exist_ok=True)
    if not diagnostics.is_file() and arguments.command != "inventory":
        raise ValueError("No JSON processing diagnostics yet. Run ./run process first.")
    store = Store.load(diagnostics) if diagnostics.is_file() else Store()
    if arguments.command == "inventory":
        result = inventory(store, root)
        store.save(diagnostics)
    elif arguments.command == "status":
        result = status(store)
    elif arguments.command in {"report", "reconcile"}:
        result = (
            coverage_report(store, arguments.club)
            if arguments.command == "report"
            else reconcile_totals(
                store, arguments.season, arguments.club, arguments.rating_decimals
            )
        )
        if arguments.output:
            write_json(arguments.output, result)
            result = {
                "output": str(arguments.output),
                "summary": result["summary"],
                **({"warnings": result["warnings"]} if "warnings" in result else {}),
            }
    elif arguments.command == "validate":
        errors = validate_records(store)
        if output.is_file():
            published = json.loads(output.read_text(encoding="utf-8"))
            expected = dashboard_data(store)
            if {
                key: value for key, value in published.items() if key != "generated_at"
            } != {
                key: value for key, value in expected.items() if key != "generated_at"
            }:
                errors.append(
                    "Published dashboard.json does not match the latest diagnostics; export the reviewed records first."
                )
        else:
            errors.append("dashboard.json is missing")
        print(json_text({"valid": not errors, "errors": errors}), end="")
        return int(bool(errors))
    elif arguments.command == "review":
        review = make_review(
            store, parse_sequences(arguments.screenshots), arguments.match
        )
        if not review["sources"]:
            raise ValueError(
                "No extractions are available for that selection; run ./run process first"
            )
        write_json(arguments.output, review, overwrite=False)
        result = {
            "review_file": str(arguments.output),
            "sources": len(review["sources"]),
        }
    elif arguments.command == "approve":
        review = json.loads(arguments.review_file.read_text(encoding="utf-8"))
        result = {
            "review": approve_review(
                store, review, arguments.note, arguments.replace_reviewed
            ),
            "message": "Saved to JSON diagnostics. Run python3 -m processing export to publish the reviewed data.",
        }
        store.save(diagnostics)
    elif arguments.command == "export":
        output = arguments.output or output
        write_json(output, dashboard_data(store))
        result = {"output": str(output)}
    elif arguments.command == "backup":
        result = backup_records(store, arguments.destination)
    print(json_text(result), end="")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as exception:
        print(f"Error: {exception}", file=sys.stderr)
        raise SystemExit(1)
