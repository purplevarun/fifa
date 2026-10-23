import hashlib
import re
from collections import Counter
from pathlib import Path

from PIL import Image

from . import SCHEMA_VERSION
from .record_schema import DEFINITIONS
from .store import EXPORT_TABLES, insert_entity


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


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
    with connection.transaction():
        for row in connection.rows("source_paths"):
            connection.update("source_paths", row["path"], {"present": False})
        for path in paths:
            if not path.resolve().is_relative_to(raw_directory.resolve()):
                raise ValueError(
                    f"Image resolves outside the screenshot directory: {path}"
                )
            sha256 = image_hash(path)
            counts["files"] += 1
            known = connection.find("source_images", sha256=sha256)
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
            connection.upsert(
                "source_paths",
                {
                    "path": path.relative_to(root).as_posix(),
                    "source_id": source_id,
                    "sequence": screenshot_sequence(path),
                    "present": True,
                },
            )
    return counts


def status(connection):
    return {
        "schema_version": SCHEMA_VERSION,
        "source_images": connection.count("source_images"),
        "present_paths": connection.count("source_paths", present=True),
        "source_states": dict(
            Counter(row["status"] for row in connection.rows("source_images"))
        ),
        "screen_types": dict(
            Counter(row["screen_type"] for row in connection.rows("source_images"))
        ),
        "records": {
            table: connection.count(table)
            for table in EXPORT_TABLES
            if not table.endswith("_sources")
        },
    }


def validate_records(connection):
    return connection.validate()


def fixture_details(connection, fixture):
    edition = connection.get("competition_seasons", fixture["competition_season_id"])
    competition = connection.get("competitions", edition["competition_id"])
    return {
        **fixture,
        "home_club": connection.get("clubs", fixture["home_club_id"])["name"],
        "away_club": connection.get("clubs", fixture["away_club_id"])["name"],
        "competition": competition["name"],
        "competition_kind": competition["kind"],
        "is_preseason": competition["is_preseason"],
        "season_id": edition["season_id"],
        "season": connection.get("seasons", edition["season_id"])["label"],
    }


def source_sequence(connection, source_id):
    sequences = [
        row["sequence"]
        for row in connection.rows("source_paths", source_id=source_id, present=True)
        if row["sequence"] is not None
    ]
    return min(sequences, default=None)


def match_precedes(connection, match_id, sequence):
    if sequence is None:
        return False
    return any(
        (number := source_sequence(connection, link["source_id"])) is not None
        and number < sequence
        for link in connection.rows("match_sources", match_id=match_id)
    )


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
        linked = {row["source_id"] for row in connection.rows(junction)}
        sources = [
            {**row, "linked": row["id"] in linked}
            for row in sorted(
                connection.rows("source_images"), key=lambda row: row["id"]
            )
            if row["screen_type"] in screen_types
        ]
        source_coverage[label] = {
            "total": len(sources),
            "linked": sum(source["linked"] for source in sources),
            "unlinked_source_ids": [
                source["id"] for source in sources if not source["linked"]
            ],
        }
    players_by_match = {}
    for row in sorted(
        connection.rows("player_matches"),
        key=lambda row: (row["match_id"], row["player_id"]),
    ):
        if (
            connection.get("clubs", row["club_id"])["name"].casefold()
            == club_name.casefold()
        ):
            players_by_match.setdefault(row["match_id"], []).append(
                {
                    **row,
                    "player_name": connection.get("players", row["player_id"])["name"],
                }
            )
    teams_by_match = {}
    for row in sorted(
        connection.rows("team_matches"),
        key=lambda row: (row["match_id"], row["club_id"]),
    ):
        teams_by_match.setdefault(row["match_id"], []).append(dict(row))
    team_fields = [
        field
        for field in DEFINITIONS["team_matches"].columns
        if field not in {"id", "match_id", "club_id"}
    ]
    fixtures = []
    for row in sorted(
        connection.rows("matches"), key=lambda row: (row["played_on"], row["id"])
    ):
        fixture = fixture_details(connection, row)
        if club_name.casefold() in {
            fixture["home_club"].casefold(),
            fixture["away_club"].casefold(),
        }:
            fixtures.append(
                {
                    **fixture,
                    "is_home": fixture["home_club"].casefold() == club_name.casefold(),
                }
            )
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
    report = {
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
    from .confirmed_context import apply_coverage_context

    return apply_coverage_context(connection, report, club_name)
