import hashlib
import json
import re
import sqlite3
from pathlib import Path

from PIL import Image

from . import SCHEMA_VERSION
from .identifiers import is_uuid, new_id
from .migrations import migrate_annual_awards, migrate_to_uuids


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
COMPETITIONS = (
    ("European International Cup", "cup", True),
    ("Invitational Cup", "cup", True),
    ("EFL League Two", "league", False),
    ("EFL League One", "league", False),
    ("EFL Championship", "league", False),
    ("UEFA Champions League", "cup", False),
    ("UEFA Europa League", "cup", False),
    ("EFL League Two Play-Offs", "cup", False),
    ("EFL League One Play-Offs", "cup", False),
    ("Carabao Cup", "cup", False),
    ("Checkatrade Trophy", "cup", False),
    ("FA Cup", "cup", False),
)
EXPORT_TABLES = (
    "players",
    "clubs",
    "seasons",
    "competitions",
    "competition_seasons",
    "matches",
    "team_matches",
    "player_matches",
    "player_snapshots",
    "player_competition_snapshots",
    "player_transfers",
    "competition_events",
    "match_sources",
    "player_match_sources",
)


def connect(database_path):
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version not in (0, 1, 2, 3, SCHEMA_VERSION):
        connection.close()
        raise ValueError(f"Unsupported database schema version: {version}")
    if version == 0:
        if connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table'"
        ).fetchone():
            connection.close()
            raise ValueError("Refusing to initialize an existing unversioned database")
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        try:
            connection.executescript(f"BEGIN;\n{schema}")
            connection.executemany(
                "INSERT INTO competitions(id, name, kind, is_preseason) VALUES (?, ?, ?, ?)",
                ((new_id(), *competition) for competition in COMPETITIONS),
            )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            connection.commit()
        except Exception:
            connection.rollback()
            connection.close()
            raise
    if version in (1, 2):
        try:
            migrate_to_uuids(
                connection,
                database_path,
                Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"),
            )
        except Exception:
            connection.close()
            raise
    if version == 3:
        try:
            migrate_annual_awards(connection)
        except Exception:
            connection.close()
            raise
    return connection


def insert_entity(connection, table, values):
    identifier = new_id()
    values = {**values, "id": identifier}
    columns = ", ".join(values)
    placeholders = ", ".join("?" for value in values)
    connection.execute(
        f"INSERT INTO {table}({columns}) VALUES ({placeholders})",
        tuple(values.values()),
    )
    return identifier


def image_hash(path):
    with Path(path).open("rb") as image_file:
        return hashlib.file_digest(image_file, "sha256").hexdigest()


def screenshot_sequence(path):
    match = re.search(r"(\d+)(?=\D*$)", Path(path).stem)
    return int(match.group(1)) if match else None


def inventory(connection, root):
    root = Path(root).resolve()
    raw_directory = root / "raw_screenshots"
    if not raw_directory.is_dir():
        raise ValueError(f"Screenshot directory does not exist: {raw_directory}")
    counts = {"files": 0, "new_images": 0, "known_images": 0, "unreadable": 0}
    paths = sorted(
        (
            path
            for path in raw_directory.rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ),
        key=lambda path: (screenshot_sequence(path) or 0, path.as_posix()),
    )
    with connection:
        connection.execute("UPDATE source_paths SET present = 0")
        for path in paths:
            if not path.resolve().is_relative_to(raw_directory.resolve()):
                raise ValueError(
                    f"Image resolves outside the screenshot directory: {path}"
                )
            sha256 = image_hash(path)
            counts["files"] += 1
            known = connection.execute(
                "SELECT id FROM source_images WHERE sha256 = ?", (sha256,)
            ).fetchone()
            if known:
                source_id = known["id"]
                counts["known_images"] += 1
            else:
                width = height = None
                error = None
                try:
                    with Image.open(path) as image:
                        width, height = image.size
                        image.verify()
                except (OSError, ValueError, SyntaxError) as exception:
                    error = str(exception)
                    counts["unreadable"] += 1
                source_id = insert_entity(
                    connection,
                    "source_images",
                    {
                        "sha256": sha256,
                        "byte_size": path.stat().st_size,
                        "width": width,
                        "height": height,
                        "status": "error" if error else "inventoried",
                        "error": error,
                    },
                )
                counts["new_images"] += 1
            connection.execute(
                "INSERT INTO source_paths(path, source_id, sequence, present) VALUES (?, ?, ?, 1) "
                "ON CONFLICT(path) DO UPDATE SET source_id = excluded.source_id, "
                "sequence = excluded.sequence, present = 1",
                (
                    path.relative_to(root).as_posix(),
                    source_id,
                    screenshot_sequence(path),
                ),
            )
    return counts


def status(connection):
    return {
        "schema_version": SCHEMA_VERSION,
        "source_images": connection.execute(
            "SELECT COUNT(*) FROM source_images"
        ).fetchone()[0],
        "present_paths": connection.execute(
            "SELECT COUNT(*) FROM source_paths WHERE present = 1"
        ).fetchone()[0],
        "source_states": dict(
            connection.execute(
                "SELECT status, COUNT(*) FROM source_images GROUP BY status"
            )
        ),
        "screen_types": dict(
            connection.execute(
                "SELECT screen_type, COUNT(*) FROM source_images GROUP BY screen_type"
            )
        ),
        "records": {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in EXPORT_TABLES
            if not table.endswith("_sources")
        },
    }


def validate_database(connection):
    errors = []
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        errors.append(integrity)
    errors.extend(
        str(tuple(row)) for row in connection.execute("PRAGMA foreign_key_check")
    )
    for table in (*EXPORT_TABLES, "source_images", "reviews"):
        if table.endswith("_sources"):
            continue
        if any(
            not is_uuid(row[0]) for row in connection.execute(f"SELECT id FROM {table}")
        ):
            errors.append(f"{table}: invalid UUID primary key")
    for table in ("team_matches", "player_matches"):
        invalid = connection.execute(
            f"SELECT record.id FROM {table} record JOIN matches fixture ON fixture.id = record.match_id "
            "WHERE record.club_id NOT IN (fixture.home_club_id, fixture.away_club_id)"
        ).fetchall()
        errors.extend(
            f"{table} {row['id']}: club is not a match participant" for row in invalid
        )
    return errors


def coverage_report(connection, club_name="Notts County"):
    source_coverage = {}
    for label, screen_types, junction in (
        ("match_summaries", ("match_facts",), "match_sources"),
        (
            "player_performances",
            ("player_performance", "goalkeeper_performance"),
            "player_match_sources",
        ),
    ):
        placeholders = ",".join("?" for screen_type in screen_types)
        sources = connection.execute(
            f"SELECT id, EXISTS(SELECT 1 FROM {junction} WHERE source_id = source_images.id) AS linked "
            f"FROM source_images WHERE screen_type IN ({placeholders}) ORDER BY id",
            screen_types,
        ).fetchall()
        source_coverage[label] = {
            "total": len(sources),
            "linked": sum(source["linked"] for source in sources),
            "unlinked_source_ids": [
                source["id"] for source in sources if not source["linked"]
            ],
        }
    players_by_match = {}
    for row in connection.execute(
        "SELECT player_matches.*, players.name AS player_name FROM player_matches JOIN clubs ON clubs.id = club_id "
        "JOIN players ON players.id = player_id "
        "WHERE clubs.name = ? COLLATE NOCASE ORDER BY match_id, player_id",
        (club_name,),
    ):
        players_by_match.setdefault(row["match_id"], []).append(dict(row))
    teams_by_match = {}
    for row in connection.execute(
        "SELECT * FROM team_matches ORDER BY match_id, club_id"
    ):
        teams_by_match.setdefault(row["match_id"], []).append(dict(row))
    team_fields = [
        row["name"]
        for row in connection.execute("PRAGMA table_info(team_matches)")
        if row["name"] not in {"id", "match_id", "club_id"}
    ]
    fixtures = connection.execute(
        "SELECT matches.*, home.name AS home_club, away.name AS away_club, "
        "competitions.name AS competition, competitions.kind AS competition_kind, "
        "competitions.is_preseason, seasons.label AS season, "
        "CASE WHEN home.name = ? COLLATE NOCASE THEN 1 ELSE 0 END AS is_home "
        "FROM matches JOIN clubs home ON home.id = home_club_id JOIN clubs away ON away.id = away_club_id "
        "JOIN competition_seasons ON competition_seasons.id = competition_season_id "
        "JOIN competitions ON competitions.id = competition_id JOIN seasons ON seasons.id = season_id "
        "WHERE home.name = ? COLLATE NOCASE OR away.name = ? COLLATE NOCASE ORDER BY played_on, matches.id",
        (club_name, club_name, club_name),
    ).fetchall()
    results = []
    warnings = []
    competitions = {}
    for fixture in fixtures:
        match_id = fixture["id"]
        players = players_by_match.get(match_id, [])
        teams = teams_by_match.get(match_id, [])
        missing_core = {}
        missing_player_details = []
        for player in players:
            fields = ["overall", "rating", "displayed_position", "assists"]
            fields += (
                ["goals_conceded", "shots_caught", "shots_parried"]
                if player["displayed_position"] == "GK"
                else ["goals", "shots_on_target", "shots_off_target"]
            )
            missing_fields = [field for field in fields if player[field] is None]
            for field in missing_fields:
                missing_core[field] = missing_core.get(field, 0) + 1
            if missing_fields:
                names = ", ".join(field.replace("_", " ") for field in missing_fields)
                missing_player_details.append(f"{player['player_name']} ({names})")
        team_complete = len(teams) == 2 and all(
            team[field] is not None for team in teams for field in team_fields
        )
        outfield = [
            player
            for player in players
            if player["displayed_position"] not in (None, "GK")
        ]
        credited_goals = None
        if outfield and all(player["goals"] is not None for player in outfield):
            credited_goals = sum(
                player["goals"] for player in players if player["goals"] is not None
            )
        goals_for = (
            fixture["home_goals"] if fixture["is_home"] else fixture["away_goals"]
        )
        goals_against = (
            fixture["away_goals"] if fixture["is_home"] else fixture["home_goals"]
        )
        difference = (
            goals_for - credited_goals
            if goals_for is not None and credited_goals is not None
            else None
        )
        assumed_own_goals = max(difference, 0) if difference is not None else None
        warning_context = {
            "match_id": match_id,
            "played_on": fixture["played_on"],
            "season": fixture["season"],
            "competition": fixture["competition"],
            "home_club": fixture["home_club"],
            "away_club": fixture["away_club"],
        }
        if difference is not None and difference < 0:
            warnings.append(
                {
                    **warning_context,
                    "code": "player_goal_difference",
                    "title": "Player goals exceed team score",
                    "team_goals": goals_for,
                    "credited_player_goals": credited_goals,
                    "difference": difference,
                    "detail": "Credited player goals exceed the team score; an opponent own goal cannot explain this difference.",
                }
            )
        if len(players) < 11:
            warnings.append(
                {
                    **warning_context,
                    "code": "fewer_than_11_player_records",
                    "title": "Fewer than 11 player records",
                    "count": len(players),
                    "detail": f"{len(players)} player appearances recorded for {club_name}; at least 11 are expected for a complete match.",
                }
            )
        if missing_core:
            warnings.append(
                {
                    **warning_context,
                    "code": "missing_player_core_fields",
                    "title": "Missing player statistics",
                    "fields": missing_core,
                    "detail": "Missing player stats: "
                    + "; ".join(missing_player_details)
                    + ".",
                }
            )
        if not team_complete:
            teams_by_club = {team["club_id"]: team for team in teams}
            missing_team_details = []
            for side in ("home", "away"):
                team = teams_by_club.get(fixture[f"{side}_club_id"])
                missing_fields = [
                    field
                    for field in team_fields
                    if team is None or team[field] is None
                ]
                if missing_fields:
                    names = ", ".join(
                        field.replace("_pct", " percentage").replace("_", " ")
                        for field in missing_fields
                    )
                    missing_team_details.append(f"{fixture[f'{side}_club']} ({names})")
            warnings.append(
                {
                    **warning_context,
                    "code": "incomplete_team_statistics",
                    "title": "Incomplete team statistics",
                    "detail": "Missing team stats: "
                    + "; ".join(missing_team_details)
                    + ".",
                }
            )
        if (
            team_complete
            and abs(sum(team["possession_pct"] for team in teams) - 100) > 0.01
        ):
            possession_total = sum(team["possession_pct"] for team in teams)
            warnings.append(
                {
                    **warning_context,
                    "code": "possession_total_mismatch",
                    "title": "Possession does not total 100%",
                    "detail": f"The two clubs' recorded possession adds up to {possession_total:g}% instead of 100%.",
                }
            )
        if goals_for is None or goals_against is None:
            missing_scores = [
                fixture[f"{side}_club"]
                for side in ("home", "away")
                if fixture[f"{side}_goals"] is None
            ]
            warnings.append(
                {
                    **warning_context,
                    "code": "missing_match_score",
                    "title": "Incomplete match score",
                    "detail": "Missing goal total for "
                    + " and ".join(missing_scores)
                    + ".",
                }
            )
        results.append(
            {
                "match_id": match_id,
                "played_on": fixture["played_on"],
                "season": fixture["season"],
                "competition": fixture["competition"],
                "is_preseason": bool(fixture["is_preseason"]),
                "home_club": fixture["home_club"],
                "away_club": fixture["away_club"],
                "player_records": len(players),
                "player_core_fields_complete": bool(players) and not missing_core,
                "team_rows": len(teams),
                "team_fields_complete": team_complete,
                "team_goals": goals_for,
                "credited_player_goals": credited_goals,
                "goal_difference": difference,
                "assumed_own_goals": assumed_own_goals,
            }
        )
        edition_key = (fixture["competition"], fixture["season"])
        edition = competitions.setdefault(
            edition_key,
            {
                "competition": fixture["competition"],
                "season": fixture["season"],
                "is_preseason": bool(fixture["is_preseason"]),
                "matches": 0,
                "known_results": 0,
                "wins": 0,
                "draws": 0,
                "losses": 0,
                "league_points_from_results": 0
                if fixture["competition_kind"] == "league"
                else None,
            },
        )
        edition["matches"] += 1
        if goals_for is not None and goals_against is not None:
            edition["known_results"] += 1
            edition[
                "wins"
                if goals_for > goals_against
                else "draws"
                if goals_for == goals_against
                else "losses"
            ] += 1
            if edition["league_points_from_results"] is not None:
                edition["league_points_from_results"] += (
                    3
                    if goals_for > goals_against
                    else 1
                    if goals_for == goals_against
                    else 0
                )
    detail_fields = (
        "passes_completed_short",
        "tackles_won",
        "interceptions",
        "minutes_played",
    )
    players = [player for group in players_by_match.values() for player in group]
    return {
        "schema_version": SCHEMA_VERSION,
        "club": club_name,
        "sources": source_coverage,
        "summary": {
            "matches": len(results),
            "preseason_matches": sum(result["is_preseason"] for result in results),
            "player_records": len(players),
            "minimum_player_records_per_match": min(
                (result["player_records"] for result in results), default=0
            ),
            "maximum_player_records_per_match": max(
                (result["player_records"] for result in results), default=0
            ),
            "matches_with_two_complete_team_rows": sum(
                result["team_fields_complete"] for result in results
            ),
            "matches_with_complete_player_core_fields": sum(
                result["player_core_fields_complete"] for result in results
            ),
            "assumed_own_goals": sum(
                result["assumed_own_goals"] or 0 for result in results
            ),
            "warning_count": len(warnings),
        },
        "player_field_availability": {
            field: {
                "recorded": sum(player[field] is not None for player in players),
                "null": sum(player[field] is None for player in players),
            }
            for field in detail_fields
        },
        "competitions": list(competitions.values()),
        "matches": results,
        "warnings": warnings,
        "limitations": [
            "Player count is coverage evidence, not proof of a starting XI or known minutes played.",
            "Positive differences between the team score and recorded player goals are assumed opponent own goals, not verified scorer attributions.",
            "Null fields may be unreviewed, absent or not applicable; they are never implied zeroes.",
            "Results use scores before penalty shootouts; league points exclude any unrecorded deductions.",
            "Opponent appearances are not included in the selected club's totals.",
        ],
    }


def json_text(value):
    return json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + "\n"
