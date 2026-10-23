"""Hash-bound owner confirmations, retained outside disposable OCR diagnostics."""

import argparse
import copy
import json
from functools import lru_cache
from pathlib import Path

POLICY_PATH = Path(__file__).with_suffix(".json")


@lru_cache(maxsize=1)
def load_context():
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if policy.get("schema_version") != 1:
        raise ValueError("Unsupported confirmed-context schema")
    return policy


def apply_record_context(source, records, policy=None):
    policy = policy or load_context()
    records = copy.deepcopy(records)
    digest = source["sha256"]
    for group in policy["season_ends"]:
        if digest not in {entry[1] for entry in group["sources"]}:
            continue
        for record in records:
            if record.get("type") not in {
                "player_snapshot",
                "player_competition_snapshot",
            }:
                continue
            if record.get("season") not in (None, group["season"]):
                raise ValueError(
                    "Confirmed end-of-season context conflicts with the source season"
                )
            record.update(
                season=group["season"],
                snapshot_kind="season_end",
                date_basis=group["basis"],
            )
            if record["type"] == "player_snapshot" and not record.get("observed_on"):
                record["date_precision"] = "season"
    interest = policy["transfer_interest"]
    if digest == interest["source"][1]:
        replacements = []
        for record in records:
            if (
                record.get("type") == "player_competition_snapshot"
                or record.get("event_type") == "transfer_interest"
            ):
                replacements.append(
                    {
                        "type": "competition_event",
                        "event_type": "transfer_interest",
                        **{
                            key: record[key]
                            for key in ("player", "player_id", "club")
                            if record.get(key)
                        },
                        "season": interest["season"],
                        "competition": interest["competition"],
                        "announced_on": None,
                        "period": interest["observed_on"],
                        "description": "Racing Club reportedly interested in signing Takefusa Kubo from Notts County. Transfer interest only, not a completed transfer. Assumed observation date: "
                        + interest["observed_on"]
                        + ". "
                        + interest["basis"],
                        "context_basis": interest["basis"],
                    }
                )
            else:
                replacements.append(record)
        records = replacements
    for check in policy["match_checks"]:
        if digest == check["source"][1]:
            for record in records:
                if record.get("type") == "match":
                    record.update(check["fields"])
    return records


def apply_coverage_context(connection, report, club, policy=None):
    policy = policy or load_context()
    if club.casefold() != "notts county":
        return report
    confirmed = {
        item["source"][1]: item["count"] for item in policy["opponent_own_goals"]
    }
    pending = {item["source"][1]: item for item in policy["pending_conflicts"]}
    pending_matches = {}
    by_match = {}
    for link in connection.rows("match_sources"):
        source = connection.get("source_images", link["source_id"])
        if source["sha256"] in confirmed:
            by_match[link["match_id"]] = confirmed[source["sha256"]]
        if source["sha256"] in pending:
            pending_matches[link["match_id"]] = pending[source["sha256"]]
    for row in report["matches"]:
        if conflict := pending_matches.get(row["match_id"]):
            report["warnings"].append(
                {
                    **{
                        key: row.get(key)
                        for key in ("match_id", "played_on", "home_club", "away_club")
                    },
                    "code": "manual_score_conflict",
                    "title": "Final score needs confirmation",
                    "detail": f"Screenshot {conflict['source'][0]}: owner reported {conflict['owner_reported']}; fresh OCR reads {conflict['fresh_ocr']}. Existing score retained pending clarification.",
                }
            )
        count = by_match.get(row["match_id"])
        row["confirmed_own_goals"] = 0
        if count is None:
            continue
        if row["goal_difference"] == count:
            row["confirmed_own_goals"] = count
            row["assumed_own_goals"] = 0
        else:
            report["warnings"].append(
                {
                    "match_id": row["match_id"],
                    "code": "confirmed_own_goal_difference",
                    "title": "Confirmed own goal does not reconcile",
                    "detail": "The owner-confirmed opponent own goal no longer explains the recorded score difference; recheck the source.",
                }
            )
    report["summary"].update(
        confirmed_own_goals=sum(
            row["confirmed_own_goals"] for row in report["matches"]
        ),
        assumed_own_goals=sum(
            row["assumed_own_goals"] or 0 for row in report["matches"]
        ),
        warning_count=len(report["warnings"]),
    )
    return report


def apply_saved_context(connection, root, policy=None):
    """Explicit maintenance: preserve entity IDs, numeric evidence and reviews."""
    from .catalog import image_hash
    from .pipeline import approve_review, make_review, select_sources
    from . import SCHEMA_VERSION

    policy = policy or load_context()
    supported = {
        entry[1] for group in policy["season_ends"] for entry in group["sources"]
    }
    supported.add(policy["transfer_interest"]["source"][1])
    supported.update(check["source"][1] for check in policy["match_checks"])
    sources = [
        source for source in select_sources(connection) if source["sha256"] in supported
    ]
    for source in sources:
        if image_hash(Path(root) / source["path"]) != source["sha256"]:
            raise ValueError(f"Image changed after review: {source['path']}")
    documents = {
        row["source_id"]: row
        for row in make_review(
            connection, source_ids={source["id"] for source in sources}
        )["sources"]
    }
    changed = []
    with connection.transaction():
        for source in sources:
            document = documents[source["id"]]
            records = apply_record_context(source, document["records"], policy)
            if records == document["records"]:
                continue
            document.update(records=records, complete=True)
            if source["sha256"] == policy["transfer_interest"]["source"][1]:
                connection.delete(
                    "player_competition_snapshots", source_id=source["id"]
                )
            approve_review(
                connection,
                {"schema_version": SCHEMA_VERSION, "sources": [document]},
                "Owner-confirmed context from processing/confirmed_context.json; raw OCR retained.",
                replace_reviewed=True,
            )
            changed.append(source["path"])
    return changed


def main():
    from .pipeline import dashboard_data
    from .store import Store, write_json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", required=True)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    path = args.root / "processing/data/diagnostics.json"
    store = Store.load(path)
    changed = apply_saved_context(store, args.root)
    exported = dashboard_data(store)
    store.save(path)
    write_json(args.root / "frontend/public/data/dashboard.json", exported)
    print(
        json.dumps(
            {
                "updated_sources": changed,
                "reconciliation": exported["season_reconciliation"]["summary"],
                "coverage": exported["match_coverage"]["summary"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
