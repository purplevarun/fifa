import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from PIL import Image

from processing import EXTRACTOR_VERSION, SCHEMA_VERSION
from processing.audit import (
    compare_independent_fields,
    screenshot_audit,
    valid_number,
    visible_field_issues,
)
from processing.catalog import inventory
from processing.record_schema import DEFINITIONS
from processing.store import Store
from processing.extraction import (
    ScreenshotExtractor,
    classify,
    parse_counts,
    parse_header,
    parse_news_event,
    parse_profile_details,
)
from processing.pipeline import (
    approve_review,
    ensure_edition,
    ensure_player,
    resolve_candidate_players,
)


class AuditParsingTests(unittest.TestCase):
    def test_signed_count_parsing_is_explicit_and_does_not_guess_invalid_cells(self):
        self.assertEqual(parse_counts("1/-1", 2), [1, None])
        self.assertEqual(parse_counts("1/-1", 2, signed=True), [1, -1])
        self.assertEqual(parse_counts("1/−1", 2, signed=True), [1, -1])
        self.assertEqual(parse_counts("1/-", 2, signed=True), [1, None])
        self.assertEqual(parse_counts("1/--1", 2, signed=True), [1, None])

    def test_new_layouts_and_competitions(self):
        self.assertEqual(classify("OFFICE > INBOX Emails"), "inbox")
        self.assertEqual(
            classify("Player Stats Rank Top Scorers"), "player_leaderboard"
        )
        self.assertEqual(classify("Player Stats Rank Assists"), "player_leaderboard")
        for text, venue in (
            ("08 July 2018  San Siro l European Int'l Cup", "San Siro"),
            ("11 January 2020 I Ivy Lane l EFL League One", "Ivy Lane"),
            ("26 October 2019/Ivy Lane/EFL League One", "Ivy Lane"),
        ):
            self.assertEqual(parse_header(text)["venue"], venue)
        for competition in (
            "EFL Championship",
            "UEFA Champions League",
            "UEFA Europa League",
        ):
            self.assertEqual(parse_header(competition)["competition"], competition)

    def test_profile_line_preserves_multiple_positions_and_nationality(self):
        self.assertEqual(
            parse_profile_details("● LW/RW/CAM/LM I Age 25 I> South Africa"),
            {
                "displayed_position": "LW/RW/CAM/LM",
                "age": 25,
                "nationality": "South Africa",
            },
        )
        self.assertEqual(
            parse_profile_details("GK Age 24 Iceland")["nationality"], "Iceland"
        )
        self.assertEqual(parse_profile_details("GK | Age 24 | Iceland")["age"], 24)
        self.assertEqual(parse_profile_details("No profile here"), {})

    def test_trophy_winner_wording(self):
        for title, club, competition in (
            (
                "Notts County Win the Checkatrade Trophy",
                "Notts County",
                "Checkatrade Trophy",
            ),
            (
                "FC Barcelona emerge as UEFA Champions League winners",
                "FC Barcelona",
                "UEFA Champions League",
            ),
            ("Roma are UEFA Europa League winners!", "Roma", "UEFA Europa League"),
        ):
            record = parse_news_event(title, announced_on="2020-05-30")
            self.assertEqual(
                (record["event_type"], record["club"], record["competition"]),
                ("champion", club, competition),
            )
        self.assertIsNone(
            parse_news_event("Notts County likely to Win the Checkatrade Trophy")
        )

    def test_alternate_individual_award_wording(self):
        record = parse_news_event(
            "Player of the Competition Announced",
            "The Checkatrade Trophy's Player of the Competition has been anounced as being Notts County's Williams",
            announced_on="2020-04-05",
        )
        self.assertEqual(record["player"], "Williams")
        self.assertEqual(record["club"], "Notts County")
        self.assertEqual(record["season"], "2019/20")


class AuditNumericTests(unittest.TestCase):
    def test_authorized_absolute_counts_do_not_rewrite_the_displayed_percentage(self):
        record = {
            "type": "player_match",
            "tackles_won": 1,
            "tackles_lost": 1,
            "tackle_accuracy_pct": 0,
            "stat_adjustments": {
                "tackles_lost": {
                    "rule": "absolute_displayed_count",
                    "displayed": -1,
                    "stored": 1,
                }
            },
        }
        issues = visible_field_issues("player_performance", [record])
        self.assertFalse(
            any(issue["code"] == "percentage_mismatch" for issue in issues)
        )
        self.assertEqual(
            (record["tackles_lost"], record["tackle_accuracy_pct"]), (1, 0)
        )
        record["stat_adjustments"]["tackles_lost"]["stored"] = 2
        issues = visible_field_issues("player_performance", [record])
        self.assertTrue(any(issue["code"] == "percentage_mismatch" for issue in issues))

    def test_club_consensus_cannot_include_a_neighbouring_score(self):
        extractor = ScreenshotExtractor(engine=object())
        extractor.recognize = Mock()
        fields = {
            "away_club": {
                "raw_text": "WALSALL",
                "confidence": 0.7,
                "box": [795 / 1366, 108 / 768, 1136 / 1366, 155 / 768],
            }
        }
        tokens = [
            {
                "text": "2 WALSALL",
                "confidence": 0.99,
                "box": [
                    [740 / 1366, 112 / 768],
                    [980 / 1366, 112 / 768],
                    [980 / 1366, 151 / 768],
                    [740 / 1366, 151 / 768],
                ],
            }
        ]
        extractor.refine_name_fields(
            Image.new("RGB", (1366, 768)), tokens, fields, ("away_club",)
        )
        self.assertEqual(fields["away_club"]["raw_text"], "WALSALL")
        extractor.recognize.assert_not_called()

    def numeric_fields(self, retry_values, initial="4", confidence=0.4):
        image = Image.new("RGB", (1366, 768), (62, 79, 122))
        image.paste("white", (8, 3, 15, 17))
        engine = Mock()
        engine.text_recognizer.side_effect = [
            ([(initial, confidence)], 0),
            (retry_values, 0),
        ]
        return ScreenshotExtractor(engine).recognize(
            image,
            {"appearances": (0, 0, 30, 20)},
            {"appearances"},
            verify_numeric=True,
        )["appearances"]

    def test_low_confidence_multidigit_dark_cell_requires_agreement(self):
        reading = self.numeric_fields([("414141", 0.9), ("4141414141", 0.9)] * 3)
        self.assertEqual(reading["raw_text"], "41")
        self.assertEqual(reading["initial_reading"]["raw_text"], "4")
        self.assertEqual(len(reading["numeric_retry"]), 6)

    def test_conflicting_retry_variants_do_not_change_a_number(self):
        reading = self.numeric_fields(
            [
                ("444", 0.9),
                ("44444", 0.9),
                ("414141", 0.9),
                ("4141414141", 0.9),
                ("", 0),
                ("", 0),
            ]
        )
        self.assertEqual(reading["raw_text"], "4")
        self.assertNotIn("initial_reading", reading)

    def test_single_retry_length_cannot_confirm_a_value(self):
        reading = self.numeric_fields([("414141", 0.9), ("", 0)] * 3, initial="")
        self.assertEqual(reading["raw_text"], "")

    def test_ranges_and_partial_leaderboards(self):
        for field, value in (
            ("overall", 0),
            ("age", 20.5),
            ("goals", -1),
            ("goals", True),
            ("rating", 10.1),
            ("pass_accuracy_pct", 101),
        ):
            self.assertFalse(valid_number(field, value))
        record = {
            "type": "player_competition_snapshot",
            "player": "Kubo",
            "club": "Notts County",
            "scope": "competition",
            "competition": "EFL League One",
            "appearances": 43,
            "goals": 23,
        }
        self.assertEqual(visible_field_issues("player_leaderboard", [record]), [])
        self.assertTrue(visible_field_issues("squad", [record]))

    def test_news_total_requires_only_the_displayed_assist_count(self):
        record = {
            "type": "player_competition_snapshot",
            "player": "Kubo",
            "club": "Notts County",
            "scope": "competition",
            "competition": None,
            "competition_kind": "league",
            "assists": 12,
        }
        self.assertEqual(visible_field_issues("news", [record]), [])
        self.assertTrue(visible_field_issues("squad", [record]))
        for value in (None, -1, "twelve"):
            with self.subTest(value=value):
                self.assertTrue(
                    visible_field_issues("news", [{**record, "assists": value}])
                )

    def test_inconsistent_counts_are_reported_not_corrected(self):
        record = {
            "type": "player_match",
            "passes_completed_short": 9,
            "passes_completed_medium": 0,
            "passes_completed_long": 0,
            "passes_failed_short": 1,
            "passes_failed_medium": 0,
            "passes_failed_long": 0,
            "pass_accuracy_pct": 60,
        }
        issues = visible_field_issues("player_performance", [record])
        self.assertTrue(any(issue["code"] == "percentage_mismatch" for issue in issues))
        self.assertEqual(record["pass_accuracy_pct"], 60)

    def test_independent_text_must_be_isolated_in_the_same_cell(self):
        evidence = {"fields": {"goals": {"raw_text": "4", "box": [0.1, 0.2, 0.2, 0.3]}}}
        token = {
            "text": "41",
            "confidence": 0.9,
            "box": [[0.11, 0.21], [0.19, 0.21], [0.19, 0.29], [0.11, 0.29]],
        }
        comparisons = compare_independent_fields(evidence, {"tokens": [token]})
        self.assertFalse(comparisons[0]["agrees"])
        self.assertEqual(
            compare_independent_fields(
                evidence, {"tokens": [{**token, "text": "Goals 4"}]}
            ),
            [],
        )
        self.assertEqual(
            compare_independent_fields(
                evidence, {"tokens": [{**token, "confidence": 0.1}]}
            ),
            [],
        )


class AuditRecordTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "raw_screenshots").mkdir()
        self.connection = Store()

    def test_every_original_is_counted_in_numeric_order_without_record_changes(self):
        for number in (10, 2, 1):
            Image.new("RGB", (12, 8), "white").save(
                self.root / f"raw_screenshots/{number}.png"
            )
        inventory(self.connection, self.root)
        before = {table: self.connection.rows(table) for table in DEFINITIONS}
        report = screenshot_audit(self.connection, self.root)
        self.assertEqual(
            [source["sequence"] for source in report["sources"]], [1, 2, 10]
        )
        self.assertEqual(report["summary"]["original_files"], 3)
        self.assertEqual(report["summary"]["distinct_images"], 1)
        self.assertEqual(report["summary"]["extracted_files"], 0)
        self.assertEqual(
            {table: self.connection.rows(table) for table in DEFINITIONS}, before
        )

    def test_changed_and_uninventoried_files_are_reported(self):
        path = self.root / "raw_screenshots/1.png"
        Image.new("RGB", (12, 8), "white").save(path)
        inventory(self.connection, self.root)
        Image.new("RGB", (12, 8), "black").save(path)
        Image.new("RGB", (12, 8), "red").save(self.root / "raw_screenshots/2.png")
        report = screenshot_audit(self.connection, self.root)
        self.assertEqual(report["summary"]["source_issue_counts"]["changed_image"], 1)
        self.assertEqual(report["summary"]["source_issue_counts"]["not_inventoried"], 1)

    def test_new_known_competition_works_in_an_existing_archive(self):
        self.connection.delete("competitions", name="EFL Championship")
        identifier = ensure_edition(
            self.connection, {"season": "2020/21", "competition": "EFL Championship"}
        )
        self.assertTrue(identifier)
        row = self.connection.find("competitions", name="EFL Championship")
        self.assertEqual((row["kind"], row["is_preseason"]), ("league", False))

    def test_leaderboard_surname_resolves_to_existing_player(self):
        player_id = ensure_player(self.connection, {"player": "Takefusa Kubo"})
        extraction = {
            "records": [{"type": "player_competition_snapshot", "player": "Kubo"}],
            "issues": [],
        }
        resolve_candidate_players(self.connection, extraction, strict=True)
        self.assertEqual(extraction["records"][0]["player_id"], player_id)

    def test_repeated_transfer_keeps_both_sources_but_not_duplicate_signings(self):
        for number, color in enumerate(("red", "green", "blue", "black"), 1):
            Image.new("RGB", (12, 8), color).save(
                self.root / f"raw_screenshots/{number}.png"
            )
        inventory(self.connection, self.root)
        sources = sorted(
            self.connection.rows("source_paths"), key=lambda row: row["sequence"]
        )
        record = {
            "type": "player_transfer",
            "player": "Test Player",
            "to_club": "Notts County",
            "transfer_type": "permanent",
            "season": "2020/21",
            "date_basis": "27/07 shown in the selected transfer row; year requires review.",
            "weekly_wage_minor": 2099900,
        }
        for source, changes in zip(
            sources, ({}, {}, {"season": "2021/22"}, {"weekly_wage_minor": 2100000})
        ):
            approve_review(
                self.connection,
                {
                    "schema_version": SCHEMA_VERSION,
                    "sources": [
                        {
                            "source_id": source["source_id"],
                            "complete": True,
                            "records": [{**record, **changes}],
                        }
                    ],
                },
                "Synthetic transfer test",
            )
        self.assertEqual(self.connection.count("reviews"), 4)
        self.assertEqual(
            self.connection.count("player_transfers"),
            3,
        )


@unittest.skipUnless(
    os.environ.get("CAREER_OCR_TESTS") == "1",
    "Set CAREER_OCR_TESTS=1 for real-image checks",
)
class AuditScreenshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.extractor = ScreenshotExtractor()
        cls.root = Path(__file__).resolve().parents[2] / "raw_screenshots"

    def extract(self, number):
        return self.extractor.extract(self.root / f"{number}.png")

    def test_all_first_season_tables_have_readable_numbers_and_balanced_totals(self):
        for number in range(908, 930):
            with self.subTest(number=number):
                result = self.extract(number)
                self.assertEqual(
                    visible_field_issues(result["screen_type"], result["records"]), []
                )
                self.assertEqual(len(result["records"]), 7)
                self.assertEqual(
                    result["evidence"]["extractor_version"], EXTRACTOR_VERSION
                )
        result = self.extract(908)
        self.assertEqual(result["records"][2]["appearances"], 41)
        self.assertEqual(result["records"][4]["appearances"], 2)

    def test_championship_header(self):
        result = self.extract(1944)
        self.assertEqual(result["records"][0]["competition"], "EFL Championship")
        self.assertEqual(result["records"][0]["played_on"], "2020-08-05")

    def test_fixture_club_names_exclude_background_prefixes(self):
        for number, club in ((1859, "Sunderland"), (1895, "Estac Troyes")):
            result = self.extract(number)
            self.assertEqual(result["records"][0]["home_club"], club)
            self.assertEqual(result["records"][0]["away_club"], "Notts County")
            self.assertIn("initial_reading", result["evidence"]["fields"]["home_club"])

    def test_leaderboards_keep_unshown_metrics_unknown(self):
        for number in range(1876, 1882):
            with self.subTest(number=number):
                result = self.extract(number)
                self.assertEqual(result["screen_type"], "player_leaderboard")
                self.assertTrue(result["records"])
                self.assertEqual(
                    visible_field_issues(result["screen_type"], result["records"]), []
                )
                for record in result["records"]:
                    self.assertNotIn("average_rating", record)
                    self.assertIsNone(record["observed_on"])
        records = self.extract(1876)["records"]
        self.assertEqual(
            [(r["player"], r["goals"], r["appearances"]) for r in records],
            [("Kubo", 23, 43), ("Calvert-Lewin", 21, 32)],
        )

    def test_dated_outbound_loan_and_user_confirmed_precontract(self):
        record = self.extract(1942)["records"][0]
        self.assertEqual(
            (record["player"], record["from_club"], record["to_club"]),
            ("Erling Braut Haaland", "Notts County", "Ajax"),
        )
        self.assertEqual(
            (record["effective_on"], record["loan_months"]), ("2020-07-22", 12)
        )
        extraction = self.extract(1587)
        transfer = extraction["records"][0]
        self.assertEqual(transfer["player"], "Seydou Doumbia")
        self.assertEqual(transfer["from_club"], "Sporting Cp")
        self.assertEqual(transfer["to_club"], "Notts County")
        self.assertEqual(transfer["transfer_type"], "permanent")
        self.assertEqual(transfer["weekly_wage_minor"], 1500000)
        self.assertIsNone(transfer["effective_on"])
        self.assertIsNone(transfer["contract_months"])
        self.assertIsNone(transfer["fee_minor"])
        self.assertIn("User-confirmed archive rule", transfer["context_basis"])
        self.assertEqual(
            extraction["evidence"]["fields"]["current_weekly_wage_minor"]["raw_text"],
            "$16,000",
        )

    def test_wrapped_award_title_does_not_become_part_of_club_name(self):
        for number, player, when in (
            (1753, "Williams", "2020-04-05"),
            (1872, "James", "2020-05-23"),
        ):
            record = self.extract(number)["records"][0]
            self.assertEqual(record["player"], player)
            self.assertEqual(record["club"], "Notts County")
            self.assertEqual(record["announced_on"], when)

    def test_negative_displayed_tackles_use_user_confirmed_absolute_values(self):
        for number in (203, 270):
            result = self.extract(number)
            record = result["records"][0]
            self.assertEqual((record["tackles_won"], record["tackles_lost"]), (1, 1))
            self.assertEqual(record["tackle_accuracy_pct"], 0)
            self.assertEqual(
                record["stat_adjustments"]["tackles_lost"]["displayed"], -1
            )
            self.assertEqual(
                visible_field_issues(result["screen_type"], result["records"]), []
            )
            self.assertIn(
                "-1",
                result["evidence"]["fields"]["tackles_won/tackles_lost"]["raw_text"],
            )
            self.assertTrue(
                any(
                    "User-confirmed absolute-count rule" in issue
                    for issue in result["issues"]
                )
            )


if __name__ == "__main__":
    unittest.main()
