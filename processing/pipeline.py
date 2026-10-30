import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

from . import EXTRACTOR_VERSION, SCHEMA_VERSION
from .confirmed_context import apply_record_context
from .catalog import (
    coverage_report,
    fixture_details,
    image_hash,
    match_precedes,
    status,
    validate_records,
)
from .record_schema import DEFINITIONS, utc_now, validate_field
from .store import COMPETITIONS, EXPORT_TABLES, insert_entity, json_text, write_json
from .identifiers import is_uuid, normalize_references
from .normalization import (
    CLUB_NAMES,
    canonical_club_name,
    identity_key,
    normalize_nationality,
    resolve_nationality,
)
from .reconciliation import player_match_goals, reconcile_totals

BOOLEAN_FIELDS = {"is_preseason", "extra_time", "started"}
NON_MATCH_SCREEN_TYPES = {
    "transfer",
    "news",
    "competition_result",
    "knockout_bracket",
    "dashboard_award",
    "inbox",
    "player_leaderboard",
}
RECORD_TABLES = {
    "match": "matches",
    "player_match": "player_matches",
    "player_snapshot": "player_snapshots",
    "player_jersey": "player_jerseys",
    "player_competition_snapshot": "player_competition_snapshots",
    "player_transfer": "player_transfers",
    "competition_event": "competition_events",
}
CONTEXT_FIELDS = {
    "type",
    "player",
    "player_id",
    "nationality",
    "nationality_basis",
    "club",
    "season",
    "competition",
    "competition_kind",
    "is_preseason",
    "home_club",
    "away_club",
    "team_stats",
    "match_source_id",
    "from_club",
    "to_club",
    "context_basis",
    "stat_adjustments",
}


def parse_sequences(value):
    if value is None:
        return None
    sequences = set()
    for part in value.split(","):
        matched = re.fullmatch(r"\s*(\d+)(?:-(\d+))?\s*", part)
        if not matched:
            raise ValueError(
                f"Invalid screenshot selection: {part!r}; use 73,76,808-810"
            )
        start = int(matched.group(1))
        end = int(matched.group(2) or start)
        if end < start or end - start > 10000:
            raise ValueError(f"Invalid screenshot range: {part}")
        sequences.update(range(start, end + 1))
    return sequences


def select_sources(connection, sequences=None, source_ids=None):
    paths = sorted(
        connection.rows("source_paths", present=True),
        key=lambda row: (
            row["sequence"] is not None,
            row["sequence"] or 0,
            row["path"],
        ),
    )
    selected = {}
    found = set()
    for path in paths:
        if source_ids is not None and path["source_id"] not in source_ids:
            continue
        if sequences is not None and path["sequence"] not in sequences:
            continue
        found.add(path["sequence"])
        if path["source_id"] not in selected:
            source = connection.get("source_images", path["source_id"])
            selected[path["source_id"]] = {
                **source,
                "path": path["path"],
                "sequence": path["sequence"],
            }
    if sequences is not None and sequences - found:
        raise ValueError(f"Screenshot numbers not found: {sorted(sequences - found)}")
    return list(selected.values())


def needs_numeric_refresh(connection, source, evidence_json):
    readings = json.loads(evidence_json).get("fields", {})
    if not readings or source["status"] == "rejected":
        return False
    from .extraction import GOALKEEPER_ROWS, OUTFIELD_ROWS, TEAM_ROWS, parse_integer

    if source["screen_type"] == "match_facts":
        fields = TEAM_ROWS
        records = []
        for link in connection.rows("match_sources", source_id=source["id"]):
            fixture = connection.get("matches", link["match_id"])
            records.extend(
                {
                    **row,
                    "side": "home"
                    if row["club_id"] == fixture["home_club_id"]
                    else "away",
                }
                for row in connection.rows("team_matches", match_id=fixture["id"])
            )
    else:
        fields = (
            GOALKEEPER_ROWS
            if source["screen_type"] == "goalkeeper_performance"
            else OUTFIELD_ROWS
        )
        records = [
            connection.get("player_matches", link["player_match_id"])
            for link in connection.rows("player_match_sources", source_id=source["id"])
        ]
    for record in records:
        for field in fields:
            if "/" in field or field.endswith("_pct") or record[field] is not None:
                continue
            key = (
                f"{record['side']}.{field}"
                if source["screen_type"] == "match_facts"
                else field
            )
            if (
                key in readings
                and parse_integer(readings[key].get("raw_text", "")) is None
            ):
                return True
    return False


def extract_pending(
    connection,
    root,
    sequences=None,
    limit=None,
    reextract=False,
    extractor=None,
    progress=None,
):
    if limit is not None and limit < 1:
        raise ValueError("The extraction limit must be at least one")
    sources = select_sources(connection, sequences)
    counts = {
        "extracted": 0,
        "skipped": 0,
        "errors": 0,
        "remaining": 0,
        "processed_source_ids": [],
    }
    attempted = 0
    for source in sources:
        existing = connection.get("extractions", source["id"])
        updated_layout = (
            existing
            and existing["extractor_version"] != EXTRACTOR_VERSION
            and source["screen_type"] in NON_MATCH_SCREEN_TYPES
        )
        if (
            existing
            and existing["extractor_version"] != EXTRACTOR_VERSION
            and source["screen_type"]
            in {"match_facts", "player_performance", "goalkeeper_performance"}
        ):
            updated_layout = needs_numeric_refresh(
                connection, source, existing["evidence_json"]
            )
        if (
            existing
            and existing["extractor_version"] != EXTRACTOR_VERSION
            and source["screen_type"] == "dashboard"
        ):
            from .extraction import classify

            tokens = json.loads(existing["evidence_json"]).get("full_image_tokens", [])
            updated_layout = (
                classify(" ".join(token["text"] for token in tokens))
                == "dashboard_award"
            )
        if existing and not reextract and not updated_layout:
            counts["skipped"] += 1
            continue
        if source["width"] is None or source["height"] is None:
            counts["errors"] += 1
            continue
        if limit is not None and attempted >= limit:
            counts["remaining"] += 1
            continue
        attempted += 1
        if extractor is None:
            from .extraction import ScreenshotExtractor

            extractor = ScreenshotExtractor()
        if progress:
            progress(f"Extracting {source['path']}")
        try:
            path = Path(root) / source["path"]
            if image_hash(path) != source["sha256"]:
                raise ValueError("Image changed after inventory; run inventory again")
            result = extractor.extract(path)
            resolve_candidate_players(connection, result)
            with connection.transaction():
                connection.upsert(
                    "extractions",
                    {
                        "source_id": source["id"],
                        "extractor_version": EXTRACTOR_VERSION,
                        "candidate_json": json_text(result["records"]),
                        "evidence_json": json_text(result["evidence"]),
                        "issues_json": json_text(result["issues"]),
                        "extracted_at": utc_now(),
                    },
                )
                connection.update(
                    "source_images",
                    source["id"],
                    {
                        "screen_type": result["screen_type"],
                        "error": None,
                        "status": source["status"]
                        if source["status"] in {"imported", "rejected"}
                        else "needs_review",
                    },
                )
            counts["extracted"] += 1
            counts["processed_source_ids"].append(source["id"])
        except Exception as exception:
            connection.update(
                "source_images",
                source["id"],
                {
                    "error": str(exception),
                    "status": "imported" if source["status"] == "imported" else "error",
                },
            )
            counts["errors"] += 1
            if progress:
                progress(f"Needs attention: {source['path']}: {exception}")
    return counts


def candidate_player_matches(connection, name):
    normalized = normalized_name(name).casefold()
    players = connection.rows("players")
    alias = connection.get("player_aliases", normalized)
    exact = [
        player
        for player in players
        if player["name"].casefold() == normalized
        or (alias and player["id"] == alias["player_id"])
    ]
    if exact:
        return exact, True
    abbreviated = re.fullmatch(r"([a-z])\.\s*(.+)", normalized)
    if abbreviated:
        initial, surname = abbreviated.groups()
        folded = identity_key(surname)
        matches = [
            player
            for player in players
            if identity_key(player["name"]).startswith(initial)
            and identity_key(player["name"]).endswith(folded)
        ]
        if matches:
            return matches, False
    return (
        [
            player
            for player in players
            if player["name"].casefold().endswith(f" {normalized}")
        ],
        False,
    )


def jersey_candidate_name(name, candidates):
    normalized = normalized_name(name).casefold()
    abbreviated = re.fullmatch(r"([a-z])\.\s*(.+)", normalized)
    if abbreviated:
        initial, surname = abbreviated.groups()
        folded = identity_key(surname)
        hits = [
            candidate
            for candidate in candidates
            if identity_key(candidate).startswith(initial)
            and identity_key(candidate).endswith(folded)
        ]
    else:
        hits = [
            candidate
            for candidate in candidates
            if candidate.casefold().endswith(f" {normalized}")
        ]
    return hits[0] if len(hits) == 1 else None


def resolve_candidate_players(connection, extraction, strict=False):
    for record in extraction["records"]:
        name = record.get("player")
        if (
            record.get("type")
            not in {
                "player_transfer",
                "competition_event",
                "player_competition_snapshot",
                "player_jersey",
            }
            or not name
            or record.get("player_id")
        ):
            continue
        matching, exact = candidate_player_matches(connection, name)
        if len(matching) == 1:
            record["player_id"] = matching[0]["id"]
            record["player"] = matching[0]["name"]
            if not exact:
                extraction["issues"].append(
                    f"OCR name {name!r} matched unambiguously to recorded player {record['player']!r}."
                )
        elif len(matching) > 1:
            if strict and record.get("type") != "player_jersey":
                raise ValueError(
                    f"Ambiguous player name {name!r}: matches multiple recorded players"
                )
            extraction["issues"].append(
                f"Ambiguous OCR player {name!r}; select the correct existing player_id during review."
            )


def make_review(connection, sequences=None, match_id=None, source_ids=None):
    if match_id is not None and (
        not is_uuid(match_id) or not connection.get("matches", match_id)
    ):
        raise ValueError(f"Unknown match ID: {match_id}")
    sources = []
    for source in select_sources(connection, sequences, source_ids):
        extraction = connection.get("extractions", source["id"])
        if not extraction:
            continue
        latest = connection.latest_review(source["id"])
        previous = json.loads(latest["payload_json"]) if latest else None
        candidates = json.loads(extraction["candidate_json"])
        records = previous["records"] if previous else candidates
        complete = previous["complete"] if previous else False
        issues = json.loads(extraction["issues_json"])
        if (
            previous
            and source["screen_type"] == "match_facts"
            and len(records) == len(candidates) == 1
            and records[0].get("type") == candidates[0].get("type") == "match"
        ):
            for side, stats in candidates[0].get("team_stats", {}).items():
                saved_stats = (
                    records[0].setdefault("team_stats", {}).setdefault(side, {})
                )
                additions = {
                    field: value
                    for field, value in stats.items()
                    if saved_stats.get(field) is None and value is not None
                }
                if additions:
                    saved_stats.update(additions)
                    complete = False
                    issues.append(
                        f"New {side} team fields were added from OCR; existing scores, fixture identity and saved values are retained."
                    )
        if (
            previous
            and source["screen_type"]
            in {"player_performance", "goalkeeper_performance"}
            and len(records) == len(candidates) == 1
            and records[0].get("type") == candidates[0].get("type") == "player_match"
        ):
            additions = {
                field: value
                for field, value in candidates[0].items()
                if field not in CONTEXT_FIELDS
                and not field.endswith("_id")
                and records[0].get(field) is None
                and value is not None
            }
            if additions:
                records[0].update(additions)
                complete = False
                issues.append(
                    "Unreviewed player fields were added from OCR; existing identities, fixture links and reviewed values are retained."
                )
        if previous and source["screen_type"] in NON_MATCH_SCREEN_TYPES:
            for candidate in candidates:
                if candidate.get("type") not in {
                    "player_transfer",
                    "competition_event",
                }:
                    continue
                key_fields = (
                    ("type", "player", "transfer_type")
                    if candidate["type"] == "player_transfer"
                    else ("type", "event_type", "player", "club", "period")
                )
                reviewed = next(
                    (
                        record
                        for record in records
                        if all(
                            record.get(field) == candidate.get(field)
                            for field in key_fields
                        )
                    ),
                    None,
                )
                if reviewed is None:
                    records.append(candidate)
                    complete = False
                else:
                    additions = {
                        field: value
                        for field, value in candidate.items()
                        if reviewed.get(field) is None and value is not None
                    }
                    if additions:
                        reviewed.update(additions)
                        complete = False
            issues.append(
                "New non-match OCR may fill unknown fields or add events; existing reviewed values are retained."
            )
        if match_id is not None:
            for record in records:
                if record.get("type") == "player_match":
                    record["match_id"] = match_id
                    record.pop("match_source_id", None)
        sources.append(
            {
                "source_id": source["id"],
                "path": source["path"],
                "screen_type": source["screen_type"],
                "complete": complete,
                "records": records,
                "issues": issues,
            }
        )
    return {"schema_version": SCHEMA_VERSION, "sources": sources}


def normalized_name(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("A non-empty name is required")
    return " ".join(value.split())


def ensure_club(connection, name):
    raw_name = normalized_name(name)
    name = canonical_club_name(raw_name)
    aliases = {raw_name.casefold(), name.casefold()}
    matches = [
        row
        for row in connection.rows("clubs")
        if canonical_club_name(row["name"]).casefold() == name.casefold()
    ]
    identifiers = {row["id"] for row in matches}
    for alias in aliases:
        existing = connection.get("club_aliases", alias)
        if existing:
            identifiers.add(existing["club_id"])
    if len(identifiers) > 1:
        raise ValueError(
            f"Duplicate club identity for {name}; rebuild or explicitly merge the existing records first"
        )
    club_id = (
        next(iter(identifiers))
        if identifiers
        else insert_entity(connection, "clubs", {"name": name})
    )
    if matches and name in CLUB_NAMES.values():
        aliases.update(row["name"].casefold() for row in matches)
        connection.update("clubs", club_id, {"name": name})
    for alias in aliases:
        connection.insert(
            "club_aliases", {"alias": alias, "club_id": club_id}, ignore=True
        )
    return club_id


def ensure_player(connection, record):
    name = normalized_name(record.get("player"))
    alias = name.casefold()
    existing = connection.get("player_aliases", alias)
    explicit_id = record.get("player_id")
    if explicit_id is not None:
        if not is_uuid(explicit_id) or not connection.get("players", explicit_id):
            raise ValueError(f"Unknown player ID: {explicit_id}")
        if existing and existing["player_id"] != explicit_id:
            raise ValueError(
                f"Player alias {name!r} already belongs to a different player"
            )
        player_id = explicit_id
    elif existing:
        player_id = existing["player_id"]
    else:
        player_id = insert_entity(connection, "players", {"name": name})
    connection.insert(
        "player_aliases", {"alias": alias, "player_id": player_id}, ignore=True
    )
    current = connection.get("players", player_id)
    saved = normalize_nationality(current["nationality"])
    nationality = normalize_nationality(record.get("nationality"))
    if nationality and saved and saved != nationality:
        raise ValueError(f"Conflicting nationality for {name}")
    if nationality is None:
        nationality = saved or resolve_nationality(current["name"])[0]
    if nationality:
        connection.update("players", player_id, {"nationality": nationality})
    return player_id


def ensure_season(connection, label):
    if not isinstance(label, str) or not re.fullmatch(r"20\d{2}/\d{2}", label):
        raise ValueError("A season such as 2018/19 is required")
    if int(label[-2:]) != (int(label[:4]) + 1) % 100:
        raise ValueError(f"Season years must be consecutive: {label}")
    existing = connection.find("seasons", label=label)
    return (
        existing["id"]
        if existing
        else insert_entity(connection, "seasons", {"label": label})
    )


def ensure_edition(connection, record):
    season_id = ensure_season(connection, record.get("season"))
    if not record.get("competition"):
        raise ValueError(
            f"A competition is required for {record.get('event_type', record.get('type', 'record'))}"
        )
    name = normalized_name(record.get("competition"))
    competition = next(
        (
            row
            for row in connection.rows("competitions")
            if row["name"].casefold() == name.casefold()
        ),
        None,
    )
    if competition is None:
        # Explicit maintenance documents may introduce a known competition.
        known = next(
            (item for item in COMPETITIONS if item[0].casefold() == name.casefold()),
            None,
        )
        if known:
            record = {"competition_kind": known[1], "is_preseason": known[2], **record}
            if (
                record["competition_kind"] != known[1]
                or type(record["is_preseason"]) is not bool
                or record["is_preseason"] != known[2]
            ):
                raise ValueError(
                    f"Classification conflicts with the known competition: {name}"
                )
        if type(record.get("is_preseason")) is not bool or record.get(
            "competition_kind"
        ) not in {"league", "cup", "friendly"}:
            raise ValueError(
                "A new competition requires competition_kind and an explicit boolean is_preseason"
            )
        competition_id = insert_entity(
            connection,
            "competitions",
            {
                "name": name,
                "kind": record["competition_kind"],
                "is_preseason": record["is_preseason"],
            },
        )
    else:
        if "is_preseason" in record and (
            type(record["is_preseason"]) is not bool
            or record["is_preseason"] != bool(competition["is_preseason"])
        ):
            raise ValueError(
                f"Preseason classification conflicts with the saved competition: {name}"
            )
        competition_id = competition["id"]
    existing = connection.find(
        "competition_seasons", competition_id=competition_id, season_id=season_id
    )
    return (
        existing["id"]
        if existing
        else insert_entity(
            connection,
            "competition_seasons",
            {
                "competition_id": competition_id,
                "season_id": season_id,
            },
        )
    )


def check_season_date(label, observed_on):
    if observed_on is None:
        return
    observed = date.fromisoformat(observed_on)
    first_year = observed.year - (observed.month < 7)
    if int(label[:4]) != first_year:
        raise ValueError(
            f"Date {observed_on} is outside the July-June career season {label}"
        )


def checked_values(connection, table, record):
    columns = DEFINITIONS[table].columns
    unknown = set(record) - set(columns) - CONTEXT_FIELDS
    if unknown:
        raise ValueError(f"Unrecognized {table} fields: {sorted(unknown)}")
    values = {
        field: value
        for field, value in record.items()
        if field in columns and field != "id"
    }
    for field, value in values.items():
        validate_field(table, field, value)
    return values


def merge_record(connection, table, values, key, replace_reviewed=False):
    existing = connection.find(table, **key)
    if existing:
        changes = {}
        for field, value in values.items():
            if field in key or value == existing[field]:
                continue
            if value is None and not replace_reviewed:
                continue
            if existing[field] is not None and not replace_reviewed:
                raise ValueError(
                    f"Conflict in {table} {existing['id']}, {field}: {existing[field]!r} versus {value!r}; "
                    "review the source and use --replace-reviewed only for an intentional correction"
                )
            changes[field] = value
        if changes:
            connection.update(table, existing["id"], changes)
        return existing["id"]
    return insert_entity(connection, table, values)


def confirmed_match(connection, record):
    match_id = record.get("match_id")
    source_id = record.get("match_source_id")
    if match_id is not None and source_id:
        raise ValueError("Supply either match_id or match_source_id, not both")
    if source_id:
        matches = connection.rows("match_sources", source_id=source_id)
        if len(matches) != 1:
            raise ValueError(
                "The referenced match screenshot must resolve to exactly one approved match"
            )
        match_id = matches[0]["match_id"]
    if not is_uuid(match_id):
        raise ValueError(
            "A verified match_id or match_source_id is required for a player appearance"
        )
    match = connection.get("matches", match_id)
    if not match:
        raise ValueError(f"Unknown match: {match_id}")
    return {
        **match,
        "season_id": connection.get(
            "competition_seasons", match["competition_season_id"]
        )["season_id"],
    }


def repeated_transfer_source(connection, record, values):
    """Deduplicate fully agreeing or complementary captures of one transfer.

    An accepted contract panel and an accepted transfer-fee panel can show the
    same signing with different visible terms. A previous transfer row is a
    duplicate when no field holds two different non-null values, ignoring the
    per-panel date basis note, and its review recorded the same season (which
    may itself be unknown at a season boundary)."""
    if not re.match(r"\d{1,2}/\d{1,2} shown in", record.get("date_basis", "")):
        return None
    existing = connection.rows(
        "player_transfers",
        **{
            field: values.get(field)
            for field in ("player_id", "transfer_type", "to_club_id", "from_club_id")
        },
    )
    for previous in existing:
        if previous["source_id"] == values["source_id"] or any(
            previous[field] is not None
            and value is not None
            and previous[field] != value
            for field, value in values.items()
            if field not in {"source_id", "date_basis"}
        ):
            continue
        review = connection.latest_review(previous["source_id"])
        if review and any(
            item.get("type") == "player_transfer"
            and item.get("season") == record.get("season")
            and item.get("player") == record.get("player")
            for item in json.loads(review["payload_json"])["records"]
        ):
            return previous
    return None


def import_record(connection, source_id, record, replace_reviewed=False):
    record_type = record.get("type")
    if record_type not in RECORD_TABLES:
        raise ValueError(f"Unsupported reviewed record type: {record_type}")
    table = RECORD_TABLES[record_type]
    values = checked_values(connection, table, record)
    if record_type == "match":
        values.update(
            competition_season_id=ensure_edition(connection, record),
            home_club_id=ensure_club(connection, record.get("home_club")),
            away_club_id=ensure_club(connection, record.get("away_club")),
        )
        if not values.get("played_on"):
            raise ValueError("An approved match needs an exact played_on date")
        check_season_date(record["season"], values["played_on"])
        key = {
            field: values[field]
            for field in (
                "competition_season_id",
                "played_on",
                "home_club_id",
                "away_club_id",
            )
        }
        link = connection.find("match_sources", source_id=source_id)
        linked = connection.get("matches", link["match_id"]) if link else None
        if linked and any(linked[field] != value for field, value in key.items()):
            raise ValueError(
                "This source already belongs to a different fixture; identity changes need separate review"
            )
        record_id = merge_record(connection, table, values, key, replace_reviewed)
        connection.insert(
            "match_sources",
            {"match_id": record_id, "source_id": source_id},
            ignore=True,
        )
        team_stats = record.get("team_stats", {})
        if not isinstance(team_stats, dict) or set(team_stats) - {"home", "away"}:
            raise ValueError("team_stats must contain only home and away objects")
        for side, stats in team_stats.items():
            team_values = checked_values(connection, "team_matches", stats)
            team_key = {"match_id": record_id, "club_id": values[f"{side}_club_id"]}
            merge_record(
                connection,
                "team_matches",
                {**team_values, **team_key},
                team_key,
                replace_reviewed,
            )
        return record_id
    if record_type == "player_match":
        fixture = confirmed_match(connection, record)
        values.update(
            match_id=fixture["id"],
            player_id=ensure_player(connection, record),
            club_id=ensure_club(connection, record.get("club")),
        )
        link = connection.find("player_match_sources", source_id=source_id)
        linked = (
            connection.get("player_matches", link["player_match_id"]) if link else None
        )
        key = {field: values[field] for field in ("match_id", "player_id")}
        if linked and any(linked[field] != value for field, value in key.items()):
            raise ValueError(
                "This performance source is already linked to a different player or match"
            )
        record_id = merge_record(connection, table, values, key, replace_reviewed)
        connection.insert(
            "player_match_sources",
            {"player_match_id": record_id, "source_id": source_id},
            ignore=True,
        )
        if "overall" in values and (values["overall"] is not None or replace_reviewed):
            snapshot_key = {
                "player_id": values["player_id"],
                "match_id": fixture["id"],
                "snapshot_kind": "in_season",
            }
            snapshot_values = {
                **snapshot_key,
                "club_id": values["club_id"],
                "season_id": fixture["season_id"],
                "source_id": source_id,
                "observed_on": fixture["played_on"],
                "date_precision": "day",
                "date_basis": f"Performance screenshot linked to approved match {fixture['id']}",
                "overall": values["overall"],
                "displayed_position": values.get("displayed_position"),
            }
            existing = connection.find("player_snapshots", **snapshot_key)
            if existing:
                snapshot_values["source_id"] = existing["source_id"]
            merge_record(
                connection,
                "player_snapshots",
                snapshot_values,
                snapshot_key,
                replace_reviewed,
            )
        return record_id
    values["source_id"] = source_id
    if record_type in {
        "player_snapshot",
        "player_competition_snapshot",
        "player_transfer",
        "player_jersey",
    }:
        values["player_id"] = ensure_player(connection, record)
    if record_type in {"player_snapshot", "player_competition_snapshot"}:
        values["season_id"] = ensure_season(connection, record.get("season"))
        values["club_id"] = (
            ensure_club(connection, record["club"]) if record.get("club") else None
        )
        check_season_date(record["season"], values.get("observed_on"))
    if record_type == "player_snapshot":
        if values.get("match_id") is not None:
            fixture = confirmed_match(connection, record)
            if (
                values["season_id"] != fixture["season_id"]
                or values.get("observed_on") != fixture["played_on"]
            ):
                raise ValueError(
                    "Snapshot date and season must agree with its linked match"
                )
        key = {
            field: values[field] for field in ("source_id", "player_id", "season_id")
        }
    elif record_type == "player_competition_snapshot":
        values["competition_season_id"] = (
            ensure_edition(connection, record)
            if record.get("scope") == "competition"
            else None
        )
        key = {
            field: values[field]
            for field in (
                "source_id",
                "player_id",
                "season_id",
                "competition_season_id",
            )
        }
    elif record_type == "player_transfer":
        values.update(
            from_club_id=ensure_club(connection, record["from_club"])
            if record.get("from_club")
            else None,
            to_club_id=ensure_club(connection, record["to_club"])
            if record.get("to_club")
            else None,
        )
        repeated = repeated_transfer_source(connection, record, values)
        if repeated:
            values["source_id"] = repeated["source_id"]
            if values.get("date_basis") != repeated["date_basis"]:
                del values["date_basis"]
        key = {
            field: values[field]
            for field in ("source_id", "player_id", "transfer_type")
        }
    elif record_type == "player_jersey":
        values["season_id"] = ensure_season(connection, record.get("season"))
        values["club_id"] = (
            ensure_club(connection, record["club"]) if record.get("club") else None
        )
        key = {field: values[field] for field in ("player_id", "season_id")}
        existing = connection.find("player_jerseys", **key)
        if existing:
            values["source_id"] = existing["source_id"]
    else:
        event_type = record.get("event_type")
        if event_type == "player_of_the_year":
            if any(
                record.get(field)
                for field in ("competition", "competition_season_id", "season")
            ):
                raise ValueError(
                    "Player of the Year is a calendar-year award, not a competition-season event"
                )
            if not isinstance(record.get("period"), str) or not re.fullmatch(
                r"20\d{2}", record["period"]
            ):
                raise ValueError(
                    "Player of the Year requires a calendar award year such as 2019"
                )
            if not record.get("player"):
                raise ValueError("Player of the Year requires a named winner")
            values["competition_season_id"] = None
        elif event_type == "transfer_interest" and not (
            record.get("season") and record.get("competition")
        ):
            # Interest is not a completed transfer or a competition award.
            values["competition_season_id"] = None
        else:
            values["competition_season_id"] = ensure_edition(connection, record)
        values["player_id"] = (
            ensure_player(connection, record) if record.get("player") else None
        )
        values["club_id"] = (
            ensure_club(connection, record["club"]) if record.get("club") else None
        )
        if event_type == "champion" and values["club_id"] is None:
            raise ValueError("A championship requires a named winning club")
        key_fields = ("source_id", "event_type", "player_id", "club_id", "period")
        award_key = None
        if event_type == "player_of_the_year":
            award_key = ("event_type", "period")
        elif event_type == "champion":
            award_key = ("event_type", "competition_season_id")
        elif event_type in {
            "player_of_the_month",
            "player_of_the_competition",
            "goalkeeper_of_the_competition",
            "golden_boot",
        }:
            award_key = ("event_type", "player_id", "period", "competition_season_id")
        elif event_type == "promotion":
            award_key = ("event_type", "club_id", "period", "competition_season_id")
        if award_key:
            key_fields = award_key
        key = {field: values.get(field) for field in key_fields}
        if award_key:
            existing = connection.find("competition_events", **key)
            if existing and existing["source_id"] != source_id:
                values["source_id"] = existing["source_id"]
                values["description"] = existing["description"]
    return merge_record(connection, table, values, key, replace_reviewed)


def approve_review(connection, document, note, replace_reviewed=False):
    if (
        not isinstance(document, dict)
        or document.get("schema_version") not in (3, SCHEMA_VERSION)
        or not isinstance(document.get("sources"), list)
    ):
        raise ValueError("Unsupported or invalid review document")
    if not isinstance(note, str) or not note.strip():
        raise ValueError("A review note is required")
    document = normalize_references(document)
    counts = {"approved_sources": 0, "skipped_reviews": 0, "reviewed_records": 0}
    seen = set()
    with connection.transaction():
        for source in document["sources"]:
            if not isinstance(source, dict) or not isinstance(
                source.get("source_id"), str
            ):
                raise ValueError("Each reviewed source needs a source_id string")
            source_id = source.get("source_id")
            if source_id in seen:
                raise ValueError(
                    "A review document cannot include the same source twice"
                )
            seen.add(source_id)
            if not connection.get("source_images", source_id):
                raise ValueError(
                    f"Source must be inventoried before review: {source_id}"
                )
            if type(source.get("complete")) is not bool:
                raise ValueError(
                    "Set complete to true or false to describe the reviewed source coverage"
                )
            records = source.get("records")
            if not isinstance(records, list) or not records:
                raise ValueError(
                    "A source needs at least one reviewed record; unsupported screens must remain queued"
                )
            payload = {"records": records, "complete": source["complete"]}
            serialized = json.dumps(
                payload, sort_keys=True, ensure_ascii=True, allow_nan=False
            )
            payload_hash = hashlib.sha256(serialized.encode()).hexdigest()
            existing = connection.find(
                "reviews", source_id=source_id, payload_hash=payload_hash
            )
            if existing and not replace_reviewed:
                counts["skipped_reviews"] += 1
                continue
            previous = connection.latest_review(source_id)
            previous_revision = previous["revision"] if previous else 0
            if replace_reviewed:
                payload_hash = hashlib.sha256(
                    f"{serialized}:correction_after:{previous_revision}".encode()
                ).hexdigest()
            for record in records:
                if not isinstance(record, dict):
                    raise ValueError("Each reviewed record must be an object")
                import_record(connection, source_id, record, replace_reviewed)
                counts["reviewed_records"] += 1
            insert_entity(
                connection,
                "reviews",
                {
                    "source_id": source_id,
                    "payload_json": serialized,
                    "payload_hash": payload_hash,
                    "note": note.strip(),
                    "revision": previous_revision + 1,
                },
            )
            connection.update(
                "source_images",
                source_id,
                {
                    "status": "imported" if source["complete"] else "needs_review",
                    "error": None,
                },
            )
            counts["approved_sources"] += 1
        # Each write validates types, relationships, ranges and uniqueness. The
        # transaction rolls back this entire review if any record fails.
    return counts


def learn_ocr_aliases(connection):
    fields = {
        "player": ("player_aliases", "player_id"),
        **{
            field: ("club_aliases", "club_id")
            for field in ("club", "home_club", "away_club", "from_club", "to_club")
        },
    }
    aliases = {}
    for extraction in connection.rows("extractions"):
        review = connection.latest_review(extraction["source_id"])
        if review is None:
            continue
        row = {**extraction, **review}
        candidates = json.loads(row["candidate_json"])
        saved = json.loads(row["payload_json"])["records"]
        if (
            len(candidates) != 1
            or len(saved) != 1
            or candidates[0].get("type") != saved[0].get("type")
        ):
            continue
        for field, (table, identifier) in fields.items():
            candidate_name, saved_name = candidates[0].get(field), saved[0].get(field)
            if (
                not isinstance(candidate_name, str)
                or not candidate_name.strip()
                or not isinstance(saved_name, str)
                or not saved_name.strip()
            ):
                continue
            alias, canonical = (
                normalized_name(candidate_name).casefold(),
                normalized_name(saved_name).casefold(),
            )
            if alias == canonical:
                continue
            existing = connection.get(table, canonical)
            if existing:
                aliases.setdefault((table, identifier, alias), set()).add(
                    existing[identifier]
                )
    with connection.transaction():
        for (table, identifier, alias), matches in aliases.items():
            if len(matches) == 1:
                connection.insert(
                    table,
                    {"alias": alias, identifier: next(iter(matches))},
                    ignore=True,
                )


def normalize_goalkeeper(connection, record):
    if record.get("goals_conceded_basis"):
        return
    displayed = record.get("goals_conceded_displayed")
    if displayed is None:
        displayed = record.get("goals_conceded")
    if displayed is None:
        return
    fixture = confirmed_match(connection, record)
    club = connection.get(
        "club_aliases", normalized_name(record.get("club")).casefold()
    )
    if club is None or club["club_id"] not in {
        fixture["home_club_id"],
        fixture["away_club_id"],
    }:
        raise ValueError("Goalkeeper club does not match either side of the fixture")
    opponent_side = "away" if club["club_id"] == fixture["home_club_id"] else "home"
    penalties, goals = (
        fixture[f"{opponent_side}_penalties"],
        fixture[f"{opponent_side}_goals"],
    )
    record["goals_conceded_displayed"] = displayed
    if penalties is None:
        record["goals_conceded_basis"] = (
            "Displayed goalkeeper count; this match had no penalty shootout."
        )
    elif goals is not None and displayed == goals + penalties:
        record["goals_conceded"] = goals
        record["goals_conceded_basis"] = (
            "Displayed goalkeeper count includes opponent shootout goals; subtract the separately recorded shootout score."
        )
    elif displayed == goals:
        record["goals_conceded_basis"] = (
            "Displayed count agrees with the opponent's score before the shootout."
        )
    else:
        raise ValueError("Ambiguous shootout-inclusive goalkeeper count")


def resolve_snapshot_league(connection, record, sequence):
    if (
        record.get("type") != "player_competition_snapshot"
        or record.get("scope") != "competition"
        or record.get("competition")
        or record.get("competition_kind") != "league"
    ):
        return
    editions = set()
    for appearance in connection.rows(
        "player_matches", player_id=record.get("player_id")
    ):
        fixture = fixture_details(
            connection, connection.get("matches", appearance["match_id"])
        )
        club = connection.get("clubs", appearance["club_id"])["name"]
        if (
            fixture["season"] == record.get("season")
            and club.casefold() == (record.get("club") or "").casefold()
            and fixture["competition_kind"] == "league"
            and match_precedes(connection, fixture["id"], sequence)
        ):
            editions.add(fixture["competition"])
    if len(editions) != 1:
        raise ValueError(
            f"Cannot determine the snapshot league for {record.get('player')!r}: "
            f"{len(editions)} matching preceding league contexts"
        )
    record["competition"] = next(iter(editions))
    record["context_basis"] = (
        f"League inferred from {record['player']}'s preceding appearances for "
        f"{record['club']} in {record['season']}; no observation date inferred."
    )


def resolve_award_context(connection, record, records):
    if record.get("type") != "competition_event" or record.get("competition"):
        return
    if record.get("event_type") != "player_of_the_month":
        if record.get("event_type") != "golden_boot" or not record.get("announced_on"):
            return
        related = [
            candidate
            for candidate in records
            if candidate.get("type") == "competition_event"
            and candidate.get("event_type")
            in {
                "champion",
                "player_of_the_competition",
                "goalkeeper_of_the_competition",
            }
            and candidate.get("competition")
            and not candidate.get("context_basis")
            and candidate.get("season") == record.get("season")
            and candidate.get("period") == record.get("period")
            and candidate.get("announced_on") == record["announced_on"]
        ]
        competitions = {candidate["competition"] for candidate in related}
        event_types = {candidate["event_type"] for candidate in related}
        if (
            len(competitions) == 1
            and "champion" in event_types
            and len(event_types) > 1
        ):
            record["competition"] = competitions.pop()
            record["context_basis"] = (
                "Competition inferred from the championship and individual award "
                f"reported on the same screen for {record['announced_on']} and {record['season']}."
            )
        return
    period = record.get("period")
    if (
        not record.get("player_id")
        or not isinstance(period, str)
        or not re.fullmatch(r"20\d{2}-\d{2}", period)
    ):
        raise ValueError(
            f"Cannot determine the monthly award competition for {record.get('player')!r}: "
            "a uniquely identified player and an exact award month are required"
        )
    editions = set()
    for appearance in connection.rows("player_matches", player_id=record["player_id"]):
        fixture = fixture_details(
            connection, connection.get("matches", appearance["match_id"])
        )
        club = connection.get("clubs", appearance["club_id"])["name"]
        if (
            fixture["played_on"][:7] == period
            and fixture["competition_kind"] == "league"
            and (record.get("season") is None or fixture["season"] == record["season"])
            and (
                record.get("club") is None
                or club.casefold() == record["club"].casefold()
            )
        ):
            editions.add((fixture["competition"], fixture["season"], club))
    if len(editions) != 1:
        raise ValueError(
            f"Cannot determine the monthly award competition for {record['player']} in {period}: "
            f"{len(editions)} matching league and club contexts"
        )
    for field, value in zip(("competition", "season", "club"), next(iter(editions))):
        if not record.get(field):
            record[field] = value
    record["context_basis"] = (
        f"Inferred from {record['player']}'s recorded league appearances in {period}."
    )


def resolve_repeated_ocr_names(connection, documents):
    corrections = {}
    for row in connection.rows("extractions"):
        fields = json.loads(row["evidence_json"]).get("fields", {})
        names = [fields.get(field, {}) for field in ("first_name", "last_name")]
        if not all(reading.get("raw_text") for reading in names) or not any(
            reading.get("method") == "rapidocr_detected_name_consensus"
            for reading in names
        ):
            continue
        original = " ".join(
            reading.get("initial_reading", reading).get("raw_text", "").strip()
            for reading in names
        )
        corrected = " ".join(reading["raw_text"].strip() for reading in names)
        if original.casefold() == corrected.casefold():
            continue
        for record in json.loads(row["candidate_json"]):
            if record.get("player") != corrected or not record.get("club"):
                continue
            key = (record["club"].casefold(), original.casefold())
            corrections.setdefault(key, {}).setdefault(corrected, set()).add(
                row["source_id"]
            )
    for document in documents.values():
        if connection.latest_review(document["source_id"]):
            continue
        for record in document["records"]:
            name = record.get("player")
            if not name or not record.get("club") or record.get("player_id"):
                continue
            choices = corrections.get((record["club"].casefold(), name.casefold()), {})
            if len(choices) != 1:
                continue
            corrected, confirming_sources = next(iter(choices.items()))
            if len(confirming_sources) < 2 or connection.get(
                "player_aliases", name.casefold()
            ):
                continue
            record["player"] = corrected
            record["context_basis"] = (
                f"OCR name {name!r} resolved as {corrected!r} from matching name-crop "
                f"consensus in {len(confirming_sources)} other screenshots for {record['club']}."
            )


def source_season_contexts(connection, sources):
    candidates = {
        row["source_id"]: json.loads(row["candidate_json"])
        for row in connection.rows("extractions")
    }
    anchors = {}
    competition_seasons = {}
    for source in sources:
        if source["sequence"] is None:
            continue
        seasons = set()
        for record in candidates.get(source["id"], []):
            season = record.get("season")
            if (
                record.get("type") != "match"
                or not isinstance(season, str)
                or not re.fullmatch(r"\d{4}/\d{2}", season)
                or not record.get("played_on")
            ):
                continue
            try:
                check_season_date(season, record["played_on"])
            except (TypeError, ValueError):
                continue
            seasons.add(season)
            if record.get("competition"):
                competition_seasons.setdefault(record["competition"], set()).add(season)
        if len(seasons) == 1:
            anchors[source["id"]] = (seasons.pop(), source["path"])
    for source in sources:
        if source["sequence"] is None:
            continue
        competitions = {
            record.get("competition")
            for record in candidates.get(source["id"], [])
            if record.get("competition")
            and (
                (
                    record.get("type") == "player_competition_snapshot"
                    and record.get("scope") == "competition"
                )
                or record.get("type") == "competition_event"
            )
        }
        if competitions and all(name in competition_seasons for name in competitions):
            seasons = set.intersection(
                *(competition_seasons[name] for name in competitions)
            )
            if len(seasons) == 1:
                anchors[source["id"]] = (
                    seasons.pop(),
                    f"{source['path']} competition tables and dated fixtures",
                )
    following = {}
    context = None
    for source in reversed(sources):
        context = anchors.get(source["id"], context)
        following[source["id"]] = context
    contexts = {}
    preceding = None
    for source in sources:
        preceding = anchors.get(source["id"], preceding)
        after = following[source["id"]]
        if source["sequence"] is None:
            continue
        if preceding and after and preceding[0] != after[0]:
            continue
        if preceding or after:
            contexts[source["id"]] = preceding or after
    return contexts


def import_pending(connection, sequences=None, refreshed_source_ids=None):
    learn_ocr_aliases(connection)
    sources = select_sources(connection)
    season_contexts = source_season_contexts(connection, sources)
    selected = {source["id"] for source in select_sources(connection, sequences)}
    refreshed = set(refreshed_source_ids or ())
    pending = {
        source["id"]
        for source in sources
        if source["id"] in selected
        and (source["status"] == "needs_review" or source["id"] in refreshed)
    }
    documents = {
        source["source_id"]: source
        for source in make_review(connection, source_ids=pending)["sources"]
    }
    resolve_repeated_ocr_names(connection, documents)
    jersey_votes = {}
    pending_names = {
        record["player"]
        for document in documents.values()
        for record in document["records"]
        if isinstance(record.get("player"), str)
        and not re.fullmatch(r"[A-Za-z0]?\..*", record["player"].strip())
    }
    for document in documents.values():
        context = season_contexts.get(document["source_id"])
        for record in document["records"]:
            name = record.get("player")
            if record.get("type") != "player_jersey" or not name:
                continue
            season = record.get("season") or (context[0] if context else None)
            if season is None:
                continue
            matching, _ = candidate_player_matches(connection, name)
            if len(matching) == 1:
                record["player_id"] = matching[0]["id"]
                record["player"] = matching[0]["name"]
            elif len(matching) > 1:
                continue
            else:
                resolved = jersey_candidate_name(name, pending_names)
                if resolved is None:
                    continue
                record["player"] = resolved
            record["context_basis"] = (
                "Abbreviated roster name resolved during import; the screenshot "
                "shows the displayed short form."
            )
            votes = jersey_votes.setdefault((record["player"], season), {})
            votes[record["squad_number"]] = votes.get(record["squad_number"], 0) + 1
    jersey_numbers = {}
    for key, votes in jersey_votes.items():
        leading = [
            number for number, count in votes.items() if count == max(votes.values())
        ]
        if len(leading) == 1:
            jersey_numbers[key] = leading[0]
    counts = {
        "imported_sources": 0,
        "imported_records": 0,
        "unchanged_sources": 0,
        "skipped_sources": [],
        "ignored_sources": [],
    }
    current_match_id = None
    for source in sources:
        screen_type = source["screen_type"]
        if (
            screen_type not in {"player_performance", "goalkeeper_performance"}
            or source["sequence"] is None
        ):
            current_match_id = None
        document = documents.get(source["id"])
        if document is not None:
            document["records"] = apply_record_context(source, document["records"])
            if not document["records"] and screen_type not in {
                "match_facts",
                "player_performance",
                "goalkeeper_performance",
                "squad",
            }:
                counts["ignored_sources"].append(
                    {
                        "path": source["path"],
                        "reason": f"No supported statistics on {screen_type} screen; OCR retained for reference",
                    }
                )
                connection.update("source_images", source["id"], {"error": None})
                continue
            try:
                if not document["records"]:
                    raise ValueError(
                        f"No supported statistics detected on {screen_type} screen"
                    )
                resolve_candidate_players(connection, document, strict=True)
                for record in document["records"]:
                    if record.get("type") == "player_transfer" and not record.get(
                        "season"
                    ):
                        context = season_contexts.get(source["id"])
                        if context:
                            record["season"] = context[0]
                    if (
                        record.get("type")
                        in {
                            "player_snapshot",
                            "player_competition_snapshot",
                            "competition_event",
                            "player_jersey",
                        }
                        and record.get("event_type") != "player_of_the_year"
                        and not record.get("season")
                    ):
                        context = season_contexts.get(source["id"])
                        if context:
                            record["season"] = context[0]
                            if record["type"] not in {
                                "competition_event",
                                "player_jersey",
                            }:
                                record["date_basis"] = (
                                    f"Season inferred from screenshot context: {context[1]}. "
                                    "No exact observation date inferred."
                                )
                    resolve_snapshot_league(connection, record, source["sequence"])
                    resolve_award_context(connection, record, document["records"])
                    if (
                        record.get("type") == "player_match"
                        and not record.get("match_id")
                        and not record.get("match_source_id")
                    ):
                        if current_match_id is None:
                            raise ValueError(
                                "No unambiguous preceding match summary for this player screenshot"
                            )
                        record["match_id"] = current_match_id
                    if (
                        screen_type == "goalkeeper_performance"
                        and record.get("type") == "player_match"
                    ):
                        normalize_goalkeeper(connection, record)
                document["records"] = [
                    record
                    for record in document["records"]
                    if record.get("type") != "player_jersey"
                    or record.get("squad_number")
                    == jersey_numbers.get((record.get("player"), record.get("season")))
                ]
                document["complete"] = True
                result = approve_review(
                    connection,
                    {"schema_version": SCHEMA_VERSION, "sources": [document]},
                    "Automatically imported by process; OCR values were not manually verified.",
                )
                counts["imported_sources"] += result["approved_sources"]
                counts["imported_records"] += result["reviewed_records"]
                counts["unchanged_sources"] += result["skipped_reviews"]
            except ValueError as exception:
                connection.update(
                    "source_images", source["id"], {"error": str(exception)}
                )
                counts["skipped_sources"].append(
                    {"path": source["path"], "reason": str(exception)}
                )
        if screen_type == "match_facts" and source["sequence"] is not None:
            matches = connection.rows("match_sources", source_id=source["id"])
            current_match_id = matches[0]["match_id"] if len(matches) == 1 else None
    return counts


def record_processing_run(connection, mode, extraction, imported):
    run = {
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "status": "partial"
        if extraction["errors"] or imported["skipped_sources"]
        else "completed",
        "extracted_images": extraction["extracted"],
        "imported_sources": imported["imported_sources"],
        "skipped_sources": len(imported["skipped_sources"]),
        "extraction_errors": extraction["errors"],
    }
    identifier = insert_entity(connection, "processing_runs", run)
    return {"id": identifier, **run}


def processing_summary(connection):
    last_run = max(
        connection.rows("processing_runs"),
        key=lambda row: row["completed_at"],
        default=None,
    )
    extracted_at = max(
        (row["extracted_at"] for row in connection.rows("extractions")), default=None
    )
    if extracted_at:
        timestamp = datetime.fromisoformat(extracted_at)
        extracted_at = (
            timestamp.replace(tzinfo=timezone.utc).isoformat()
            if timestamp.tzinfo is None
            else timestamp.isoformat()
        )
    return {"last_run": last_run, "last_extracted_at": extracted_at}


def build_dataset(connection):
    errors = validate_records(connection)
    if errors:
        raise ValueError("Cannot export invalid records: " + "; ".join(errors))
    data = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "processing": processing_summary(connection),
        "coverage": status(connection),
        "match_coverage": coverage_report(connection),
        "season_reconciliation": reconcile_totals(connection),
    }
    for table in EXPORT_TABLES:
        ordering = DEFINITIONS[table].primary
        rows = sorted(
            connection.rows(table),
            key=lambda row: tuple(row[field] for field in ordering),
        )
        for row in rows:
            if table == "players" and row.get("nationality") is not None:
                row["nationality"] = normalize_nationality(row["nationality"])
            for field in BOOLEAN_FIELDS & row.keys():
                if row[field] is not None:
                    row[field] = bool(row[field])
            if table == "player_matches":
                goals = player_match_goals(row)
                row["goals_assumed_zero"] = row["goals"] is None and goals == 0
                row["goals"] = goals
        data[table] = rows
    data["source_images"] = []
    for source in connection.rows("source_images"):
        paths = connection.rows("source_paths", source_id=source["id"])
        present = [row["path"] for row in paths if row["present"]]
        data["source_images"].append(
            {
                **{
                    field: source[field]
                    for field in ("id", "sha256", "screen_type", "status")
                },
                "path": min(present or [row["path"] for row in paths], default=None),
                "available": bool(present),
            }
        )
    data["source_images"].sort(key=lambda row: row["path"] or "")
    return data


def dashboard_data(connection):
    data = build_dataset(connection)
    for field in ("source_images", "match_sources", "player_match_sources"):
        data.pop(field)
    data["coverage"] = {"records": data["coverage"]["records"]}
    data["match_coverage"].pop("sources", None)

    def public_value(value):
        if isinstance(value, list):
            return [public_value(item) for item in value]
        if isinstance(value, dict):
            return {
                key: public_value(item)
                for key, item in value.items()
                if key
                not in {
                    "source_id",
                    "match_source_id",
                    "date_basis",
                    "goals_conceded_basis",
                }
            }
        return value

    return public_value(data)


def export_data(connection, output_path):
    data = build_dataset(connection)
    write_json(output_path, data)
    return {
        "output": str(output_path),
        "matches": len(data["matches"]),
        "player_matches": len(data["player_matches"]),
        "player_snapshots": len(data["player_snapshots"]),
    }


def backup_records(connection, destination):
    connection.save(destination, overwrite=False)
    return {"backup": str(destination)}
