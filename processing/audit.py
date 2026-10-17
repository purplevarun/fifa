"""Read-only, per-original OCR coverage and consistency checks.

Passing these checks is not a claim of human visual verification. In particular,
two OCR readers can agree on an incorrect value, and absent context stays unknown.
"""

import argparse
import json
import math
import re
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from .database import (
    IMAGE_EXTENSIONS,
    coverage_report,
    image_hash,
    screenshot_sequence,
    validate_database,
)
from .extraction import (
    GOALKEEPER_ROWS,
    OUTFIELD_ROWS,
    TEAM_ROWS,
    parse_number,
)
from .pipeline import write_json
from .reconciliation import reconcile_totals

TOTAL_FIELDS = (
    "appearances",
    "goals",
    "assists",
    "clean_sheets",
    "yellow_cards",
    "red_cards",
)


def summed(record, fields):
    values = [record.get(field) for field in fields]
    return (
        sum(values)
        if all(type(value) in (int, float) and math.isfinite(value) for value in values)
        else None
    )


def valid_number(field, value):
    upper = {"rating": 10, "average_rating": 10, "age": 99, "overall": 99}.get(field)
    if field.endswith("_pct"):
        upper = 100
    if type(value) not in (int, float) or not math.isfinite(value):
        return False
    if value < 0 or (upper is not None and value > upper):
        return False
    integral = not field.endswith("_pct") and field not in {"rating", "average_rating"}
    return not integral or (
        type(value) is int and (field not in {"age", "overall"} or value > 0)
    )


def displayed_tackle_counts(record):
    """Check the screenshot's percentage against its original displayed counts."""
    displayed = dict(record)
    for field in ("tackles_won", "tackles_lost"):
        adjustment = record.get("stat_adjustments", {}).get(field, {})
        original = adjustment.get("displayed")
        if (
            adjustment.get("rule") == "absolute_displayed_count"
            and type(original) is int
            and original < 0
            and adjustment.get("stored") == record.get(field) == abs(original)
        ):
            displayed[field] = original
    return displayed


class FieldChecks:
    def __init__(self, issues, prefix):
        self.issues, self.prefix = issues, prefix

    def issue(self, code, field, detail, **values):
        self.issues.append(
            {"code": code, "field": self.prefix + field, "detail": detail, **values}
        )

    def required(self, record, fields):
        for field in fields:
            if record.get(field) is None or record.get(field) == "":
                self.issue(
                    "missing_visible_field",
                    field,
                    "Expected on-screen field was not read; inspect its visibility and evidence.",
                )

    def numbers(self, record, fields):
        for field in fields:
            value = record.get(field)
            if value is not None and not valid_number(field, value):
                self.issue(
                    "invalid_visible_number",
                    field,
                    "Invalid numeric value.",
                    value=value,
                )

    def ratio(self, record, field, numerator, denominator):
        value = record.get(field)
        if not all(
            type(item) in (int, float) and math.isfinite(item)
            for item in (value, numerator, denominator)
        ):
            return
        expected = 100 * numerator / denominator if denominator else 0
        # Allow displayed integer truncation or rounding; never "fix" the OCR
        # simply to make arithmetic agree.
        if abs(value - expected) >= 1.01:
            self.issue(
                "percentage_mismatch",
                field,
                "Percentage disagrees with displayed counts.",
                value=value,
                calculated=round(expected, 3),
            )

    def match(self, record, _screen_type):
        self.required(
            record,
            (
                "played_on",
                "season",
                "competition",
                "home_club",
                "away_club",
                "home_goals",
                "away_goals",
                "venue",
            ),
        )
        self.numbers(
            record, ("home_goals", "away_goals", "home_penalties", "away_penalties")
        )
        for side in ("home", "away"):
            team = record.get("team_stats", {}).get(side, {})
            checks = FieldChecks(self.issues, self.prefix + f"team_stats.{side}.")
            checks.required(team, TEAM_ROWS)
            checks.numbers(team, TEAM_ROWS)
            checks.ratio(
                team,
                "shot_accuracy_pct",
                team.get("shots_on_target"),
                team.get("shots"),
            )
        possessions = [
            record.get("team_stats", {}).get(side, {}).get("possession_pct")
            for side in ("home", "away")
        ]
        if (
            all(value is not None for value in possessions)
            and abs(sum(possessions) - 100) > 0.01
        ):
            self.issue(
                "possession_total_mismatch",
                "team_stats",
                "Possession does not total 100%.",
                value=sum(possessions),
            )

    def player(self, record, screen_type):
        rows = (
            GOALKEEPER_ROWS
            if screen_type == "goalkeeper_performance"
            else OUTFIELD_ROWS
        )
        fields = [part for field in rows for part in field.split("/")]
        self.required(
            record,
            ("player", "club", "overall", "rating", "displayed_position", *fields),
        )
        self.numbers(record, ("overall", "rating", *fields))
        completed = summed(
            record,
            (
                f"passes_completed_{distance}"
                for distance in ("short", "medium", "long")
            ),
        )
        attempted = summed(
            record,
            (
                f"passes_{outcome}_{distance}"
                for outcome in ("completed", "failed")
                for distance in ("short", "medium", "long")
            ),
        )
        self.ratio(record, "pass_accuracy_pct", completed, attempted)
        self.ratio(
            record,
            "shot_accuracy_pct",
            record.get("shots_on_target"),
            summed(record, ("shots_on_target", "shots_off_target")),
        )
        displayed = displayed_tackle_counts(record)
        self.ratio(
            record,
            "tackle_accuracy_pct",
            displayed.get("tackles_won"),
            summed(displayed, ("tackles_won", "tackles_lost")),
        )

    def profile(self, record, _screen_type):
        self.required(
            record,
            ("player", "club", "overall", "age", "displayed_position", "nationality"),
        )
        self.numbers(record, ("overall", "age"))

    def snapshot(self, record, screen_type):
        metrics = TOTAL_FIELDS
        if screen_type == "player_leaderboard":
            metrics = (
                "appearances",
                *(field for field in ("goals", "assists") if field in record),
            )
        self.required(record, ("player", "club", *metrics))
        if record.get("scope") == "competition":
            self.required(record, ("competition",))
        if screen_type != "player_leaderboard" and record.get("appearances", 0):
            self.required(record, ("average_rating",))
        self.numbers(record, (*metrics, "average_rating"))


def visible_field_issues(screen_type, records):
    """Check only fields that the supported screen actually displays."""
    issues = []
    handlers = {
        "match": "match",
        "player_match": "player",
        "player_snapshot": "profile",
        "player_competition_snapshot": "snapshot",
    }
    for index, record in enumerate(records):
        handler = handlers.get(record.get("type"))
        if handler:
            getattr(FieldChecks(issues, f"records.{index}."), handler)(
                record, screen_type
            )
    issues.extend(snapshot_total_issues(records))
    return issues


def snapshot_total_issues(records):
    issues = []
    checks = FieldChecks(issues, "")
    totals = [
        record
        for record in records
        if record.get("type") == "player_competition_snapshot"
    ]
    aggregate = [
        record for record in totals if record.get("scope") == "all_competitions"
    ]
    parts = [record for record in totals if record.get("scope") == "competition"]
    if len(aggregate) == 1 and parts:
        for field in TOTAL_FIELDS:
            values = [record.get(field) for record in parts]
            value = aggregate[0].get(field)
            if (
                value is not None
                and all(part is not None for part in values)
                and sum(values) != value
            ):
                checks.issue(
                    "snapshot_total_mismatch",
                    field,
                    "Competition rows do not sum to the displayed total.",
                    value=value,
                    calculated=sum(values),
                )
    return issues


def numeric_value(field, raw):
    if "/" not in field:
        return parse_number(raw)
    parts = raw.replace(" ", "").split("/")
    if len(parts) == len(field.split("/")) and all(
        re.fullmatch(r"-?\d+", part) for part in parts
    ):
        return [int(part) for part in parts]
    return None


def token_in_cell(token, bounds):
    left, top, right, bottom = bounds
    xs, ys = zip(*token["box"])
    return (
        token.get("confidence", 0) >= 0.7
        and left - 3 / 1366 <= min(xs) <= max(xs) <= right + 3 / 1366
        and top - 3 / 768 <= min(ys) <= max(ys) <= bottom + 3 / 768
    )


def compare_independent_fields(evidence, independent):
    """Compare numeric cells only where the second reader isolated the same cell.

    A line containing both a label and a number is not a cell reading. Unmatched
    cells are counted as unverified, never silently treated as agreement.
    """
    comparisons = []
    for field, reading in evidence.get("fields", {}).items():
        raw = reading.get("raw_text", "").strip()
        value = numeric_value(field, raw)
        if value is None:
            continue
        bounds = reading.get("box")
        if not bounds:
            continue
        matches = []
        for token in independent.get("tokens", []):
            if token_in_cell(token, bounds):
                text = token["text"].strip()
                other = numeric_value(field, text)
                if other is not None:
                    matches.append((other, text))
        if len(matches) == 1:
            other, text = matches[0]
            comparisons.append(
                {
                    "field": field,
                    "primary": value,
                    "independent": other,
                    "independent_text": text,
                    "agrees": value == other,
                }
            )
    return comparisons


def saved_sources(connection):
    return {
        row["path"]: dict(row)
        for row in connection.execute(
            "SELECT p.path, p.sequence, s.id, s.sha256, s.screen_type, s.status, s.error, "
            "e.candidate_json, e.evidence_json, e.issues_json, e.extractor_version, r.payload_json, r.note "
            "FROM source_paths p JOIN source_images s ON s.id=p.source_id "
            "LEFT JOIN extractions e ON e.source_id=s.id "
            "LEFT JOIN reviews r ON r.source_id=s.id AND r.revision="
            "(SELECT MAX(previous.revision) FROM reviews previous WHERE previous.source_id=s.id) "
            "WHERE p.present=1"
        )
    }


def audit_source_extraction(source, row, second):
    records = json.loads(row["candidate_json"])
    evidence = json.loads(row["evidence_json"])
    source["record_count"] = len(records)
    source["ocr_issues"] = json.loads(row["issues_json"])
    source["user_confirmed_adjustments"] = {
        f"records.{index}.{field}": adjustment
        for index, record in enumerate(records)
        for field, adjustment in record.get("stat_adjustments", {}).items()
    }
    source["user_confirmed_assumptions"] = [
        record["context_basis"]
        for record in records
        if record.get("context_basis", "").startswith("User-confirmed archive rule:")
    ]
    source["field_issues"] = visible_field_issues(row["screen_type"], records)
    source["low_confidence_fields"] = [
        field
        for field, reading in evidence.get("fields", {}).items()
        if reading.get("confidence", 0) < 0.85
    ]
    source["numeric_fields_read"] = sum(
        numeric_value(field, reading.get("raw_text", "")) is not None
        for field, reading in evidence.get("fields", {}).items()
    )
    if not records:
        source["issues"].append(
            {
                "code": "no_records",
                "detail": "No supported record extracted; this is not verified scraping coverage.",
            }
        )
    elif row["status"] != "imported":
        source["issues"].append(
            {
                "code": "not_imported",
                "detail": "Extracted records have not all been imported.",
            }
        )
    payload = json.loads(row["payload_json"]) if row["payload_json"] else None
    source["saved_field_issues"] = (
        visible_field_issues(row["screen_type"], payload["records"])
        if payload
        else None
    )
    source["independent_comparisons"] = []
    if second is not None:
        source["independent_error"] = second.get("error")
        source["independent_comparisons"] = compare_independent_fields(evidence, second)
    source["independent_unmatched_numeric_fields"] = source[
        "numeric_fields_read"
    ] - len(source["independent_comparisons"])


def audit_source(path, root, row, second):
    source = {
        "path": path.relative_to(root).as_posix(),
        "sequence": screenshot_sequence(path),
        "issues": [],
    }
    try:
        with Image.open(path) as image:
            source["dimensions"] = list(image.size)
            image.verify()
        source["sha256"] = image_hash(path)
    except (OSError, ValueError, SyntaxError) as exception:
        source["issues"].append({"code": "unreadable_image", "detail": str(exception)})
        return source
    if row is None:
        source["issues"].append(
            {
                "code": "not_inventoried",
                "detail": "Original has not been inventoried in this database.",
            }
        )
        return source
    source.update(
        source_id=row["id"],
        screen_type=row["screen_type"],
        import_status=row["status"],
        extractor_version=row["extractor_version"],
    )
    if source["sha256"] != row["sha256"]:
        source["issues"].append(
            {
                "code": "changed_image",
                "detail": "Original no longer matches its OCR evidence.",
            }
        )
    if row["error"]:
        source["issues"].append({"code": "processing_error", "detail": row["error"]})
    if row["candidate_json"] is None:
        source["issues"].append(
            {"code": "not_extracted", "detail": "No OCR extraction exists."}
        )
    else:
        audit_source_extraction(source, row, second)
    return source


def audit_summary(sources):
    problems = [issue for source in sources for issue in source["issues"]]
    fields = [issue for source in sources for issue in source.get("field_issues", [])]
    comparisons = [
        comparison
        for source in sources
        for comparison in source.get("independent_comparisons", [])
    ]
    return {
        "original_files": len(sources),
        "distinct_images": len(
            {source["sha256"] for source in sources if "sha256" in source}
        ),
        "extracted_files": sum("record_count" in source for source in sources),
        "files_with_records": sum(
            source.get("record_count", 0) > 0 for source in sources
        ),
        "imported_files": sum(
            source.get("import_status") == "imported" for source in sources
        ),
        "files_with_field_issues": sum(
            bool(source.get("field_issues")) for source in sources
        ),
        "source_issue_counts": dict(Counter(issue["code"] for issue in problems)),
        "field_issue_counts": dict(Counter(issue["code"] for issue in fields)),
        "independent_files": sum("independent_error" in source for source in sources),
        "independent_errors": sum(
            bool(source.get("independent_error")) for source in sources
        ),
        "numeric_fields_read": sum(
            source.get("numeric_fields_read", 0) for source in sources
        ),
        "independent_numeric_comparisons": len(comparisons),
        "independent_numeric_disagreements": sum(
            not comparison["agrees"] for comparison in comparisons
        ),
        "independent_unmatched_numeric_fields": sum(
            source.get("independent_unmatched_numeric_fields", 0) for source in sources
        ),
    }


def ordered_snapshot_comparisons(connection):
    """Diagnostic comparison to preceding captures, without inventing a date.

    This relies on the archive's confirmed chronological order. It does not
    relabel an undated snapshot as season_end or change canonical reconciliation.
    """
    comparisons = []
    snapshots = connection.execute(
        "SELECT totals.*, player.name AS player, MIN(path.sequence) AS sequence "
        "FROM player_competition_snapshots totals JOIN players player ON player.id=totals.player_id "
        "JOIN source_paths path ON path.source_id=totals.source_id AND path.present=1 "
        "GROUP BY totals.id ORDER BY sequence, totals.id"
    ).fetchall()
    for snapshot in snapshots:
        if snapshot["sequence"] is None:
            comparisons.append(
                {
                    "source_id": snapshot["source_id"],
                    "sequence": None,
                    "player": snapshot["player"],
                    "metrics": {},
                    "reason": "No numeric screenshot sequence; cutoff cannot be established.",
                }
            )
            continue
        appearances = connection.execute(
            "SELECT appearance.* FROM player_matches appearance JOIN matches fixture ON fixture.id=appearance.match_id "
            "JOIN competition_seasons edition ON edition.id=fixture.competition_season_id "
            "WHERE appearance.player_id=? AND appearance.club_id=? AND edition.season_id=? "
            "AND (? IS NULL OR fixture.competition_season_id=?) "
            "AND EXISTS(SELECT 1 FROM match_sources link JOIN source_paths path ON path.source_id=link.source_id "
            "WHERE link.match_id=fixture.id AND path.present=1 AND path.sequence<?)",
            (
                snapshot["player_id"],
                snapshot["club_id"],
                snapshot["season_id"],
                snapshot["competition_season_id"],
                snapshot["competition_season_id"],
                snapshot["sequence"],
            ),
        ).fetchall()
        metrics = {
            "appearances": {
                "captured": snapshot["appearances"],
                "preceding_records": len(appearances),
            }
        }
        for field in ("goals", "assists"):
            values = [appearance[field] for appearance in appearances]
            if field == "goals":
                values = [
                    0
                    if value is None
                    and (row["played_position"] or row["displayed_position"]) == "GK"
                    else value
                    for value, row in zip(values, appearances)
                ]
            derived = (
                sum(values) if all(value is not None for value in values) else None
            )
            metrics[field] = {"captured": snapshot[field], "preceding_records": derived}
        for metric in metrics.values():
            metric["result"] = "not_comparable"
            if (
                metric["captured"] is not None
                and metric["preceding_records"] is not None
            ):
                metric["result"] = (
                    "match"
                    if metric["captured"] == metric["preceding_records"]
                    else "mismatch"
                )
        comparisons.append(
            {
                "source_id": snapshot["source_id"],
                "sequence": snapshot["sequence"],
                "player": snapshot["player"],
                "scope": snapshot["scope"],
                "competition_season_id": snapshot["competition_season_id"],
                "metrics": metrics,
            }
        )
    return {
        "basis": "Compare cumulative counts with unique appearances in preceding screenshots of the same club, season and competition. Assumes the user-confirmed chronological order, not an exact observation date. Goalkeeper missing goals use the documented zero assumption.",
        "metric_counts": dict(
            Counter(
                metric["result"]
                for comparison in comparisons
                for metric in comparison["metrics"].values()
            )
        ),
        "comparisons": comparisons,
    }


def screenshot_audit(connection, root, independent=None):
    root = Path(root).resolve()
    independent = independent or {}
    saved = saved_sources(connection)
    files = sorted(
        (
            path
            for path in (root / "raw_screenshots").rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ),
        key=lambda path: (screenshot_sequence(path) or 0, path.as_posix()),
    )
    sources = [
        audit_source(
            path,
            root,
            saved.get(path.relative_to(root).as_posix()),
            independent.get(path.relative_to(root).as_posix())
            or independent.get(path.name),
        )
        for path in files
    ]
    coverage = coverage_report(connection)
    dated = reconcile_totals(connection)
    ordered = ordered_snapshot_comparisons(connection)
    summary = audit_summary(sources)
    summary.update(
        match_coverage_warnings=len(coverage["warnings"]),
        dated_snapshot_mismatches=dated["summary"]["mismatched_rows"],
        ordered_snapshot_mismatches=ordered["metric_counts"].get("mismatch", 0),
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "database_errors": validate_database(connection),
        "match_coverage": coverage,
        "season_reconciliation": dated,
        "ordered_snapshot_comparisons": ordered,
        "sources": sources,
        "limitations": [
            "Automated evidence audit, not human visual verification or a guarantee of correctness.",
            "OCR confidence and agreement do not prove correctness; unmatched independent cells are unverified.",
            "Missing dates, minutes, starting status and off-screen information are not invented.",
            "Unconfirmed snapshot cutoffs cannot be reported as matching season totals.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--db", type=Path)
    parser.add_argument(
        "--independent",
        type=Path,
        help="Optional JSONL from an independent OCR reader (path, tokens, error).",
    )
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    database = (
        arguments.db or arguments.root / "processing/data/career.sqlite"
    ).resolve()
    independent = {}
    if arguments.independent:
        with arguments.independent.open(encoding="utf-8") as stream:
            for line in stream:
                reading = json.loads(line)
                independent[reading["path"]] = reading
    with closing(
        sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    ) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        report = screenshot_audit(connection, arguments.root, independent)
    write_json(arguments.output, report)
    print(json.dumps(report["summary"], indent=2))
    summary = report["summary"]
    failed = (
        report["database_errors"]
        or summary["source_issue_counts"]
        or summary["field_issue_counts"]
        or summary["independent_numeric_disagreements"]
        or summary["independent_errors"]
        or summary["match_coverage_warnings"]
        or summary["dated_snapshot_mismatches"]
        or summary["ordered_snapshot_mismatches"]
    )
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
