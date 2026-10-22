from collections import Counter
from decimal import Decimal, ROUND_DOWN

from . import SCHEMA_VERSION
from .catalog import fixture_details


def player_match_goals(performance):
    goals = performance["goals"]
    position = performance["played_position"] or performance["displayed_position"]
    return 0 if goals is None and position == "GK" else goals


def compare_metric(observed, derived, missing=0):
    if observed is None:
        result = "not_captured"
    elif missing or derived is None:
        result = "not_comparable"
    else:
        result = "match" if observed == derived else "mismatch"
    return {
        "observed": observed,
        "derived": derived,
        "missing_match_values": missing,
        "result": result,
        "difference": derived - observed
        if observed is not None and derived is not None
        else None,
    }


def reconcile_totals(connection, season=None, club="Notts County", rating_decimals=1):
    if rating_decimals not in (1, 2):
        raise ValueError("Rating display precision must be one or two decimal places")
    snapshots = []
    for row in connection.rows("player_competition_snapshots"):
        club_name = connection.get("clubs", row["club_id"])["name"]
        season_label = connection.get("seasons", row["season_id"])["label"]
        if club_name.casefold() != club.casefold() or (
            season is not None and season != season_label
        ):
            continue
        edition = connection.get("competition_seasons", row["competition_season_id"])
        snapshots.append(
            {
                **row,
                "player": connection.get("players", row["player_id"])["name"],
                "club": club_name,
                "season": season_label,
                "competition": connection.get(
                    "competitions", edition["competition_id"]
                )["name"]
                if edition
                else None,
            }
        )
    snapshots.sort(
        key=lambda row: tuple(
            row[field] or ""
            for field in ("season", "player", "scope", "competition", "observed_on")
        )
    )
    fixtures = {
        row["id"]: fixture_details(connection, row)
        for row in connection.rows("matches")
    }
    appearances = connection.rows("player_matches")
    comparisons = []
    metric_counts = {
        field: Counter()
        for field in ("appearances", "goals", "assists", "average_rating")
    }
    for snapshot in snapshots:
        comparison = {
            field: snapshot[field]
            for field in (
                "player_id",
                "player",
                "club",
                "season",
                "scope",
                "competition",
                "source_id",
                "observed_on",
                "snapshot_kind",
                "date_basis",
            )
        }
        comparison["snapshot_id"] = snapshot["id"]
        if (
            snapshot["observed_on"] is None
            and snapshot["snapshot_kind"] != "season_end"
        ):
            comparison.update(result="unconfirmed_cutoff", metrics={})
            comparisons.append(comparison)
            continue
        performances = [
            row
            for row in appearances
            if row["player_id"] == snapshot["player_id"]
            and row["club_id"] == snapshot["club_id"]
            and fixtures[row["match_id"]]["season_id"] == snapshot["season_id"]
            and (
                snapshot["scope"] != "competition"
                or fixtures[row["match_id"]]["competition_season_id"]
                == snapshot["competition_season_id"]
            )
            and (
                snapshot["observed_on"] is None
                or fixtures[row["match_id"]]["played_on"] <= snapshot["observed_on"]
            )
        ]
        performances.sort(
            key=lambda row: (fixtures[row["match_id"]]["played_on"], row["id"])
        )
        metrics = {
            "appearances": compare_metric(snapshot["appearances"], len(performances))
        }
        for field in ("goals", "assists"):
            match_values = [
                player_match_goals(performance)
                if field == "goals"
                else performance[field]
                for performance in performances
            ]
            missing = sum(value is None for value in match_values)
            derived = sum(match_values) if not missing else None
            metrics[field] = compare_metric(snapshot[field], derived, missing)
            if field == "goals":
                metrics[field]["assumed_zero_match_values"] = sum(
                    performance["goals"] is None and value == 0
                    for performance, value in zip(performances, match_values)
                )
        missing_ratings = sum(
            performance["rating"] is None for performance in performances
        )
        average = displayed_average = None
        if performances and not missing_ratings:
            average = sum(
                Decimal(str(performance["rating"])) for performance in performances
            ) / len(performances)
            displayed_average = average.quantize(
                Decimal(1).scaleb(-rating_decimals), rounding=ROUND_DOWN
            )
        rating = compare_metric(
            snapshot["average_rating"],
            float(displayed_average) if displayed_average is not None else None,
            missing_ratings,
        )
        rating.update(
            raw_match_average=float(average) if average is not None else None,
            display_rule=f"Truncate the mean to {rating_decimals} decimal place(s); keep the unrounded mean separately.",
        )
        if (
            not performances
            and snapshot["appearances"] == 0
            and snapshot["average_rating"] in (0, None)
        ):
            rating["result"] = "not_applicable"
        metrics["average_rating"] = rating
        for field, metric in metrics.items():
            metric_counts[field][metric["result"]] += 1
        states = {metric["result"] for metric in metrics.values()}
        comparison["result"] = (
            "mismatch"
            if "mismatch" in states
            else "partial_comparison"
            if states & {"not_comparable", "not_captured"}
            else "match"
        )
        comparison["metrics"] = metrics
        comparisons.append(comparison)
    season_totals = [
        comparison
        for comparison in comparisons
        if comparison["scope"] == "all_competitions"
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "club": club,
        "season": season,
        "summary": {
            "snapshot_rows": len(comparisons),
            "players": len({comparison["player_id"] for comparison in comparisons}),
            "season_total_rows": len(season_totals),
            "mismatched_rows": sum(
                comparison["result"] == "mismatch" for comparison in comparisons
            ),
            "partial_comparisons": sum(
                comparison["result"] == "partial_comparison"
                for comparison in comparisons
            ),
            "unconfirmed_cutoffs": sum(
                comparison["result"] == "unconfirmed_cutoff"
                for comparison in comparisons
            ),
            "metrics": {field: dict(counts) for field, counts in metric_counts.items()},
        },
        "comparisons": comparisons,
        "limitations": [
            "Snapshot totals are compared with, never added to, unique player-match records for the same club, season and competition scope.",
            "All-competition comparisons include preseason games belonging to that season.",
            "An undated in-season observation cannot be compared until its cutoff is confirmed.",
            "The one-decimal truncation rule matches the observed first-season display; the raw average remains visible and other editions may use different formatting.",
            "Missing goals scored are treated as zero for goalkeeper appearances; recorded goals are retained. Unknown outfield goals remain not comparable.",
            "Passes and blocks have no season-end counterpart; cards and outfield clean sheets are retained without inventing unobserved match events or participation times.",
        ],
    }
