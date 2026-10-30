"""Typed record definitions and invariants for the in-memory screenshot archive."""

import json
import math
import re
from datetime import date, datetime, timezone

from .identifiers import REFERENCE_TABLES, is_uuid


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def fields(text="", integer="", number="", boolean=""):
    return {
        **dict.fromkeys(text.split(), "text"),
        **dict.fromkeys(integer.split(), "integer"),
        **dict.fromkeys(number.split(), "number"),
        **dict.fromkeys(boolean.split(), "boolean"),
    }


class Definition:
    def __init__(self, columns, required="", primary="id", unique=(), defaults=None):
        self.primary = tuple(primary.split())
        self.columns = {**({"id": "text"} if primary == "id" else {}), **columns}
        self.required = set(required.split()) | set(self.primary)
        self.unique = (self.primary, *(tuple(key.split()) for key in unique))
        self.defaults = defaults or {}


DEFINITIONS = {
    "source_images": Definition(
        fields("sha256 screen_type status error created_at", "byte_size width height"),
        "sha256 byte_size screen_type status created_at",
        unique=("sha256",),
        defaults={
            "screen_type": "unknown",
            "status": "inventoried",
            "created_at": utc_now,
        },
    ),
    "source_paths": Definition(
        fields("path source_id", "sequence", boolean="present"),
        "source_id present",
        primary="path",
        defaults={"present": True},
    ),
    "extractions": Definition(
        fields(
            "source_id extractor_version candidate_json evidence_json issues_json extracted_at"
        ),
        "extractor_version candidate_json evidence_json issues_json extracted_at",
        primary="source_id",
        defaults={"extracted_at": utc_now},
    ),
    "reviews": Definition(
        fields("source_id payload_json payload_hash note reviewed_at", "revision"),
        "source_id payload_json payload_hash note reviewed_at revision",
        unique=("source_id payload_hash", "source_id revision"),
        defaults={"reviewed_at": utc_now},
    ),
    "players": Definition(fields("name nationality"), "name"),
    "player_aliases": Definition(
        fields("alias player_id"), "player_id", primary="alias"
    ),
    "clubs": Definition(fields("name"), "name", unique=("name",)),
    "club_aliases": Definition(fields("alias club_id"), "club_id", primary="alias"),
    "seasons": Definition(fields("label"), "label", unique=("label",)),
    "competitions": Definition(
        fields("name kind", boolean="is_preseason"),
        "name kind is_preseason",
        unique=("name",),
    ),
    "competition_seasons": Definition(
        fields("competition_id season_id"),
        "competition_id season_id",
        unique=("competition_id season_id",),
    ),
    "matches": Definition(
        fields(
            "competition_season_id played_on home_club_id away_club_id venue round",
            "home_goals away_goals home_penalties away_penalties duration_minutes",
            boolean="extra_time",
        ),
        "competition_season_id played_on home_club_id away_club_id",
        unique=("competition_season_id played_on home_club_id away_club_id",),
    ),
    "match_sources": Definition(
        fields("match_id source_id"), primary="match_id source_id"
    ),
    "team_matches": Definition(
        fields(
            "match_id club_id",
            "shots shots_on_target tackles fouls corners",
            "possession_pct shot_accuracy_pct pass_accuracy_pct",
        ),
        "match_id club_id",
        unique=("match_id club_id",),
    ),
    "player_matches": Definition(
        fields(
            "match_id player_id club_id displayed_position played_position goals_conceded_basis",
            "overall minutes_played goals assists shots_on_target shots_off_target "
            "passes_completed_short passes_completed_medium passes_completed_long "
            "passes_failed_short passes_failed_medium passes_failed_long key_passes "
            "crosses_successful crosses_failed tackles_won tackles_lost fouls penalties_conceded "
            "interceptions blocks out_of_position possession_won possession_lost clearances "
            "headers_won headers_lost key_dribbles fouled successful_dribbles goals_conceded "
            "goals_conceded_displayed shots_caught shots_parried crosses_caught balls_stripped",
            "rating pass_accuracy_pct shot_accuracy_pct tackle_accuracy_pct",
            "started",
        ),
        "match_id player_id club_id",
        unique=("match_id player_id",),
    ),
    "player_match_sources": Definition(
        fields("player_match_id source_id"), primary="player_match_id source_id"
    ),
    "player_snapshots": Definition(
        fields(
            "player_id season_id club_id source_id match_id snapshot_kind observed_on date_from date_to "
            "date_precision date_basis displayed_position squad_role",
            "overall age",
        ),
        "player_id season_id source_id snapshot_kind date_precision date_basis",
        unique=("player_id season_id source_id snapshot_kind",),
    ),
    "player_jerseys": Definition(
        fields("player_id club_id season_id source_id", "squad_number"),
        "player_id club_id season_id source_id squad_number",
        unique=("player_id season_id",),
    ),
    "player_competition_snapshots": Definition(
        fields(
            "player_id club_id season_id competition_season_id source_id observed_on snapshot_kind date_basis scope",
            "appearances goals assists clean_sheets yellow_cards red_cards",
            "average_rating",
        ),
        "player_id club_id season_id source_id snapshot_kind date_basis scope",
        defaults={
            "snapshot_kind": "in_season",
            "date_basis": "Observation cutoff not yet confirmed",
        },
    ),
    "player_transfers": Definition(
        fields(
            "player_id from_club_id to_club_id source_id transfer_type effective_on date_basis currency currency_display",
            "fee_minor weekly_wage_minor contract_months loan_months",
        ),
        "player_id source_id transfer_type date_basis",
    ),
    "competition_events": Definition(
        fields(
            "competition_season_id source_id event_type player_id club_id announced_on period description"
        ),
        "source_id event_type description",
    ),
    "processing_runs": Definition(
        fields(
            "completed_at mode status",
            "extracted_images imported_sources skipped_sources extraction_errors",
        ),
        "completed_at mode status extracted_images imported_sources skipped_sources extraction_errors",
    ),
}


ENUMS = {
    ("source_images", "status"): {
        "inventoried",
        "needs_review",
        "imported",
        "rejected",
        "error",
    },
    ("competitions", "kind"): {"league", "cup", "friendly"},
    ("player_snapshots", "snapshot_kind"): {
        "season_start",
        "season_end",
        "in_season",
        "first_observed",
        "arrival",
    },
    ("player_snapshots", "date_precision"): {"day", "range", "season", "unknown"},
    ("player_competition_snapshots", "snapshot_kind"): {"in_season", "season_end"},
    ("player_competition_snapshots", "scope"): {"competition", "all_competitions"},
    ("player_transfers", "transfer_type"): {"permanent", "loan", "loan_return"},
    ("processing_runs", "mode"): {"clean"},
    ("processing_runs", "status"): {"completed", "partial"},
}


def validate_field(table, field, value):
    if value is None:
        return
    kind = DEFINITIONS[table].columns[field]
    label = f"{table}.{field}"
    if kind == "integer" and type(value) is not int:
        raise ValueError(f"{label} must be an integer or null")
    if kind == "number" and (
        type(value) not in (int, float) or not math.isfinite(value)
    ):
        raise ValueError(f"{label} must be a finite number or null")
    if kind == "boolean" and type(value) is not bool:
        raise ValueError(f"{label} must be a boolean or null")
    if kind == "text" and not isinstance(value, str):
        raise ValueError(f"{label} must be text or null")
    if (field == "id" or field in REFERENCE_TABLES) and not is_uuid(value):
        raise ValueError(f"{label} must be a canonical UUID")
    if field.endswith("_on") or field in {"date_from", "date_to"}:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError(f"{label} must use YYYY-MM-DD")
    if kind in {"integer", "number"}:
        lower = (
            1
            if field
            in {
                "width",
                "height",
                "revision",
                "overall",
                "age",
                "duration_minutes",
                "contract_months",
                "loan_months",
                "squad_number",
            }
            else 0
        )
        upper = (
            100
            if field.endswith("_pct")
            else 99
            if field in {"overall", "age", "squad_number"}
            else 10
            if field in {"rating", "average_rating"}
            else None
        )
        if value < lower or (upper is not None and value > upper):
            raise ValueError(f"{label} is outside its supported range")
    if (table, field) in ENUMS and value not in ENUMS[table, field]:
        raise ValueError(f"Invalid {label}: {value!r}")
    if field in {"name", "note"} and not value.strip():
        raise ValueError(f"{label} must not be blank")
    if field.endswith("_json"):
        parsed = json.loads(value)
        expected = list if field in {"candidate_json", "issues_json"} else dict
        if not isinstance(parsed, expected):
            raise ValueError(f"{label} must contain a JSON {expected.__name__}")
        json.dumps(parsed, allow_nan=False)


def validate_record(table, row, store):
    definition = DEFINITIONS[table]
    if set(row) != set(definition.columns):
        raise ValueError(f"{table}: unrecognized or missing fields")
    for field, value in row.items():
        if value is None and field in definition.required:
            raise ValueError(f"{table}.{field} is required")
        validate_field(table, field, value)
        target = REFERENCE_TABLES.get(field)
        if value is not None and target and store.get(target, value) is None:
            raise ValueError(f"{table}.{field}: missing {target} record {value}")
    if table == "source_images" and not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
        raise ValueError("source_images.sha256 must be a SHA-256 hex digest")
    if table == "matches":
        if row["home_club_id"] == row["away_club_id"]:
            raise ValueError("A match requires two different clubs")
        for suffix in ("goals", "penalties"):
            if (row[f"home_{suffix}"] is None) != (row[f"away_{suffix}"] is None):
                raise ValueError(f"Both match {suffix} must be recorded together")
        if row["home_penalties"] is not None and (
            row["home_goals"] is None
            or row["home_goals"] != row["away_goals"]
            or row["home_penalties"] == row["away_penalties"]
        ):
            raise ValueError(
                "A shootout requires a tied match and unequal penalty scores"
            )
    if table in {"team_matches", "player_matches"}:
        fixture = store.get("matches", row["match_id"])
        if row["club_id"] not in {fixture["home_club_id"], fixture["away_club_id"]}:
            raise ValueError("Club must participate in the match")
    if (
        table == "team_matches"
        and row["shots"] is not None
        and row["shots_on_target"] is not None
        and row["shots_on_target"] > row["shots"]
    ):
        raise ValueError("Shots on target cannot exceed total shots")
    if table == "player_snapshots":
        if not row["date_basis"].strip():
            raise ValueError("Snapshot date basis is required")
        if (row["date_precision"] == "day") != (row["observed_on"] is not None):
            raise ValueError(
                "Snapshot day precision requires an exact observation date"
            )
        if row["date_precision"] == "range" and (
            row["date_from"] is None
            or row["date_to"] is None
            or row["date_from"] > row["date_to"]
        ):
            raise ValueError("Snapshot range requires ordered date boundaries")
    if table == "player_competition_snapshots" and (row["scope"] == "competition") != (
        row["competition_season_id"] is not None
    ):
        raise ValueError("Competition snapshot scope requires a competition edition")
    if table == "player_transfers":
        if row["from_club_id"] == row["to_club_id"]:
            raise ValueError(
                "A transfer requires at least one club and different source/destination clubs"
            )
    if table == "competition_events":
        if row["event_type"] == "player_of_the_year":
            if (
                row["competition_season_id"] is not None
                or row["player_id"] is None
                or not re.fullmatch(r"20\d{2}", row["period"] or "")
            ):
                raise ValueError(
                    "Player of the Year requires a winner and calendar year, not a competition edition"
                )
        elif row["competition_season_id"] is None:
            raise ValueError("Competition events require a competition edition")
