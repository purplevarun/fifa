import copy
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

from processing import EXTRACTOR_VERSION
from processing.catalog import (
    coverage_report,
    fixture_details,
    inventory,
    status,
    validate_records,
)
from processing.store import Store, insert_entity
from processing.record_schema import DEFINITIONS
from processing.pipeline import (
    approve_review,
    backup_records,
    dashboard_data,
    ensure_player,
    ensure_club,
    ensure_edition,
    ensure_season,
    export_data,
    extract_pending,
    import_pending,
    make_review,
)
from processing.batch_review import fixture_contexts, prepare_player_cores
from processing.identifiers import is_uuid, new_id
from processing.extraction import parse_news_event
from processing.reconciliation import reconcile_totals


class RecordTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.raw = self.root / "raw_screenshots"
        self.raw.mkdir()
        self.store = Store()

    def update_records(self, table, values, **filters):
        with self.store.transaction():
            for row in self.store.rows(table, **filters):
                key = tuple(row[field] for field in DEFINITIONS[table].primary)
                self.store.update(table, key, values)

    def create_image(self, name="Screenshot (73).png", color="white"):
        path = self.raw / name
        Image.new("RGB", (40, 20), color).save(path)
        return path

    def create_match(self):
        self.season_id = ensure_season(self.store, "2018/19")
        self.edition_id = ensure_edition(
            self.store,
            {"competition": "European International Cup", "season": "2018/19"},
        )
        self.home_club_id = ensure_club(self.store, "Notts County")
        self.away_club_id = ensure_club(self.store, "Dundee FC")
        self.other_club_id = ensure_club(self.store, "Other Club")
        self.match_id = insert_entity(
            self.store,
            "matches",
            {
                "competition_season_id": self.edition_id,
                "played_on": "2018-07-04",
                "home_club_id": self.home_club_id,
                "away_club_id": self.away_club_id,
                "home_goals": 1,
                "away_goals": 1,
            },
        )
        return self.match_id

    def create_player(self, name="Aaron Ramsdale"):
        return insert_entity(self.store, "players", {"name": name})


class RecordTests(RecordTestCase):
    def test_json_reopen_preserves_existing_records(self):
        match_id = self.create_match()
        player_id = self.create_player()
        appearance_id = insert_entity(
            self.store,
            "player_matches",
            {
                "match_id": match_id,
                "player_id": player_id,
                "club_id": self.home_club_id,
                "goals_conceded": 2,
                "goals_conceded_displayed": 2,
            },
        )
        path = self.root / "diagnostics.json"
        self.store.save(path)
        self.store = Store.load(path)
        row = self.store.get("player_matches", appearance_id)
        self.assertTrue(is_uuid(appearance_id))
        self.assertEqual(
            (row["goals_conceded"], row["goals_conceded_displayed"]), (2, 2)
        )
        self.assertEqual(validate_records(self.store), [])

    def test_empty_coverage_has_no_invented_matches(self):
        report = coverage_report(self.store)
        self.assertEqual(report["summary"]["matches"], 0)
        self.assertEqual(report["summary"]["minimum_player_records_per_match"], 0)
        self.assertEqual(report["warnings"], [])

    def test_player_nationality_ignores_ocr_prefix_noise(self):
        for name, raw_nationality, expected in (
            ("Takefusa Kubo", "ge 17 Ip Japan", "Japan"),
            ("Thembinkosi Lorch", "Age 25 1 South Africa", "South Africa"),
        ):
            with self.subTest(name=name):
                player_id = insert_entity(self.store, "players", {"name": name})
                ensure_player(
                    self.store,
                    {
                        "player_id": player_id,
                        "player": name,
                        "nationality": raw_nationality,
                    },
                )
                self.assertEqual(
                    self.store.get("players", player_id)["nationality"],
                    expected,
                )

    def test_dashboard_contains_stats_without_screenshot_references(self):
        self.create_image()
        inventory(self.store, self.root)
        source_id = self.store.find("source_images")["id"]
        match_id = self.create_match()
        player_id = self.create_player()
        insert_entity(
            self.store,
            "player_snapshots",
            {
                "player_id": player_id,
                "season_id": self.season_id,
                "source_id": source_id,
                "snapshot_kind": "first_observed",
                "date_precision": "season",
                "date_basis": "Screenshot (73).png",
                "overall": 62,
            },
        )
        dataset = dashboard_data(self.store)
        self.assertEqual(dataset["matches"][0]["id"], match_id)
        self.assertEqual(dataset["player_snapshots"][0]["overall"], 62)
        for field in ("source_images", "match_sources", "player_match_sources"):
            self.assertNotIn(field, dataset)
        self.assertNotIn("sources", dataset["match_coverage"])
        serialized = json.dumps(dataset)
        self.assertNotIn(source_id, serialized)
        self.assertNotIn("Screenshot (73).png", serialized)
        self.assertNotIn('"source_id"', serialized)

    def test_inventory_is_content_based_and_repeatable(self):
        original = self.create_image()
        shutil.copyfile(original, self.raw / "Screenshot (74).png")
        first = inventory(self.store, self.root)
        self.assertEqual(first["new_images"], 1)
        self.assertEqual(first["files"], 2)
        self.update_records("source_images", {"status": "imported"})
        second = inventory(self.store, self.root)
        self.assertEqual(second["new_images"], 0)
        self.assertEqual(status(self.store)["source_states"], {"imported": 1})
        original.rename(self.raw / "Screenshot (75).png")
        inventory(self.store, self.root)
        self.assertEqual(status(self.store)["source_images"], 1)
        self.assertEqual(status(self.store)["present_paths"], 2)

    def test_changed_image_keeps_old_source_history(self):
        self.create_image()
        inventory(self.store, self.root)
        self.create_image(color="black")
        inventory(self.store, self.root)
        self.assertEqual(status(self.store)["source_images"], 2)
        self.assertEqual(status(self.store)["present_paths"], 1)

    def test_deleted_screenshots_and_reused_names_preserve_saved_matches(self):
        original = self.create_image()
        original_bytes = original.read_bytes()
        self.raw = self.raw.rename(self.root / "raw_screenshots")
        original = self.raw / original.name
        inventory(self.store, self.root)
        source_id = self.store.find("source_images")["id"]
        match_id = self.create_match()
        self.store.insert(
            "match_sources", {"match_id": match_id, "source_id": source_id}
        )
        self.update_records("source_images", {"status": "imported"})

        original.unlink()
        self.assertEqual(inventory(self.store, self.root)["new_images"], 0)
        self.assertEqual(status(self.store)["present_paths"], 0)
        self.assertEqual(status(self.store)["records"]["matches"], 1)

        Image.new("RGB", (40, 20), "black").save(original)
        self.assertEqual(inventory(self.store, self.root)["new_images"], 1)
        self.assertEqual(status(self.store)["source_images"], 2)
        self.assertEqual(
            self.store.find("match_sources")["source_id"],
            source_id,
        )

        original.unlink()
        (self.raw / "renamed.png").write_bytes(original_bytes)
        self.assertEqual(inventory(self.store, self.root)["new_images"], 0)
        self.assertEqual(
            status(self.store)["source_states"], {"imported": 1, "inventoried": 1}
        )
        self.assertEqual(validate_records(self.store), [])

    def test_corrupt_image_is_reported(self):
        (self.raw / "broken.png").write_bytes(b"not an image")
        self.assertEqual(inventory(self.store, self.root)["unreadable"], 1)
        self.assertEqual(status(self.store)["source_states"], {"error": 1})

    def test_competitions_require_boolean_preseason(self):
        self.assertEqual(
            self.store.count("competitions", is_preseason=True),
            2,
        )
        with self.assertRaises(ValueError):
            insert_entity(
                self.store,
                "competitions",
                {"name": "Invalid", "kind": "cup", "is_preseason": 2},
            )

    def test_matches_cannot_have_missing_competition(self):
        self.create_match()
        for edition in (None, new_id()):
            with self.assertRaises(ValueError):
                insert_entity(
                    self.store,
                    "matches",
                    {
                        "competition_season_id": edition,
                        "played_on": "2018-07-05",
                        "home_club_id": self.home_club_id,
                        "away_club_id": self.away_club_id,
                    },
                )

    def test_appearance_must_belong_to_participating_club(self):
        match_id = self.create_match()
        player_id = self.create_player("Takefusa Kubo")
        with self.assertRaises(ValueError):
            insert_entity(
                self.store,
                "player_matches",
                {
                    "match_id": match_id,
                    "player_id": player_id,
                    "club_id": self.other_club_id,
                },
            )
        insert_entity(
            self.store,
            "player_matches",
            {
                "match_id": match_id,
                "player_id": player_id,
                "club_id": self.home_club_id,
            },
        )
        with self.assertRaises(ValueError):
            insert_entity(
                self.store,
                "player_matches",
                {
                    "match_id": match_id,
                    "player_id": player_id,
                    "club_id": self.home_club_id,
                },
            )
        self.assertEqual(validate_records(self.store), [])

    def test_snapshot_requires_supported_date_precision(self):
        self.create_image()
        inventory(self.store, self.root)
        self.create_match()
        player_id = self.create_player()
        source_id = self.store.find("source_images")["id"]
        snapshot = {
            "player_id": player_id,
            "season_id": self.season_id,
            "source_id": source_id,
            "snapshot_kind": "season_start",
            "date_precision": "day",
            "date_basis": "Date missing",
        }
        with self.assertRaises(ValueError):
            insert_entity(self.store, "player_snapshots", snapshot)
        insert_entity(
            self.store,
            "player_snapshots",
            {
                **snapshot,
                "snapshot_kind": "first_observed",
                "date_precision": "season",
                "date_basis": "Opening squad screen, exact day unknown",
                "overall": 62,
            },
        )
        self.assertEqual(
            self.store.find("player_snapshots")["observed_on"],
            None,
        )


class ImportTests(RecordTestCase):
    def prepare_source(self, sequence, color):
        self.create_image(f"Screenshot ({sequence}).png", color)
        inventory(self.store, self.root)
        return self.store.find("source_paths", sequence=sequence)["source_id"]

    def review(self, source_id, records, complete=True):
        return {
            "schema_version": 3,
            "sources": [
                {"source_id": source_id, "complete": complete, "records": records}
            ],
        }

    def match_record(self):
        return {
            "type": "match",
            "competition": "European International Cup",
            "season": "2018/19",
            "played_on": "2018-07-04",
            "home_club": "Notts County",
            "away_club": "Dundee FC",
            "home_goals": 1,
            "away_goals": 1,
            "team_stats": {"home": {"shots": 6}, "away": {"fouls": 0}},
        }

    def approved_match(self):
        source_id = self.prepare_source(73, "white")
        document = self.review(source_id, [self.match_record()])
        approve_review(self.store, document, "Verified against the screenshot")
        fixture = self.store.find("matches")
        self.match_id = fixture["id"]
        self.home_club_id = fixture["home_club_id"]
        return source_id, document

    def test_review_is_repeatable_and_competition_is_preseason(self):
        source_id, document = self.approved_match()
        result = approve_review(self.store, document, "Repeated import")
        self.assertEqual(result["skipped_reviews"], 1)
        self.assertEqual(status(self.store)["records"]["matches"], 1)
        self.assertEqual(status(self.store)["records"]["team_matches"], 2)
        self.assertEqual(
            fixture_details(self.store, self.store.find("matches"))["is_preseason"],
            1,
        )

    def test_different_capture_merges_same_match(self):
        self.approved_match()
        source_id = self.prepare_source(74, "gray")
        approve_review(
            self.store,
            self.review(source_id, [self.match_record()]),
            "Duplicate capture, visually checked",
        )
        self.assertEqual(status(self.store)["records"]["matches"], 1)
        self.assertEqual(
            self.store.count("match_sources"),
            2,
        )

    def test_player_import_links_match_and_preserves_history(self):
        match_source, document = self.approved_match()
        player_source = self.prepare_source(76, "black")
        player = {
            "type": "player_match",
            "match_source_id": match_source,
            "player": "Takefusa Kubo",
            "club": "Notts County",
            "overall": 63,
            "rating": 8.4,
            "goals": 0,
            "assists": 1,
        }
        review = self.review(player_source, [player])
        approve_review(self.store, review, "Player and fixture checked")
        approve_review(self.store, review, "Rerun")
        self.assertEqual(status(self.store)["records"]["player_matches"], 1)
        snapshot = self.store.find("player_snapshots")
        self.assertEqual(snapshot["overall"], 63)
        self.assertEqual(snapshot["observed_on"], "2018-07-04")
        self.assertEqual(snapshot["snapshot_kind"], "in_season")
        extra_source = self.prepare_source(77, "blue")
        approve_review(
            self.store,
            self.review(extra_source, [player]),
            "Same player, second capture",
        )
        self.assertEqual(status(self.store)["records"]["player_snapshots"], 1)

    def test_conflicts_require_explicit_correction(self):
        source_id, original = self.approved_match()
        corrected = copy.deepcopy(original)
        corrected["sources"][0]["records"][0]["home_goals"] = 2
        with self.assertRaisesRegex(ValueError, "Conflict"):
            approve_review(self.store, corrected, "Unapproved conflicting value")
        self.assertEqual(self.store.find("matches")["home_goals"], 1)
        approve_review(
            self.store,
            corrected,
            "Intentional visual correction",
            replace_reviewed=True,
        )
        self.assertEqual(self.store.find("matches")["home_goals"], 2)
        approve_review(
            self.store, original, "Older review must not undo newer correction"
        )
        self.assertEqual(self.store.find("matches")["home_goals"], 2)

    def test_failed_batch_rolls_back_all_records(self):
        source_id = self.prepare_source(73, "white")
        bad_player = {
            "type": "player_match",
            "match_id": 999,
            "player": "Unknown",
            "club": "Notts County",
        }
        with self.assertRaises(ValueError):
            approve_review(
                self.store,
                self.review(source_id, [self.match_record(), bad_player]),
                "Invalid batch",
            )
        self.assertEqual(status(self.store)["records"]["matches"], 0)
        self.assertEqual(status(self.store)["records"]["clubs"], 0)
        self.assertEqual(self.store.count("reviews"), 0)

    def test_unknown_fields_and_string_numbers_are_rejected(self):
        source_id = self.prepare_source(73, "white")
        for update in ({"home_goals": "1"}, {"home_goal": 1}, {"home_goals": True}):
            with self.assertRaises(ValueError):
                approve_review(
                    self.store,
                    self.review(source_id, [{**self.match_record(), **update}]),
                    "Invalid data",
                )
        self.assertEqual(status(self.store)["records"]["matches"], 0)

    def test_match_date_must_belong_to_its_competition_season(self):
        source_id = self.prepare_source(73, "white")
        record = {**self.match_record(), "season": "2019/20"}
        with self.assertRaisesRegex(ValueError, "outside"):
            approve_review(self.store, self.review(source_id, [record]), "Wrong season")
        self.assertEqual(status(self.store)["records"]["matches"], 0)

    def test_new_competition_requires_explicit_classification(self):
        source_id = self.prepare_source(73, "white")
        record = {**self.match_record(), "competition": "Preseason Friendlies"}
        with self.assertRaises(ValueError):
            approve_review(
                self.store,
                self.review(source_id, [record]),
                "Missing classification",
            )
        record.update(is_preseason=True, competition_kind="friendly")
        approve_review(
            self.store,
            self.review(source_id, [record]),
            "Verified standalone preseason friendly",
        )
        self.assertEqual(status(self.store)["records"]["matches"], 1)

    def test_club_alias_resolves_to_same_uuid_without_duplicate_club(self):
        self.approved_match()
        self.store.insert(
            "club_aliases", {"alias": "nottscounty", "club_id": self.home_club_id}
        )
        self.assertEqual(ensure_club(self.store, "NottsCounty"), self.home_club_id)
        self.assertEqual(ensure_club(self.store, "NOTTS COUNTY"), self.home_club_id)
        self.assertTrue(is_uuid(self.home_club_id))
        self.assertEqual(self.store.count("clubs"), 2)

    def test_extraction_never_overwrites_approved_data(self):
        source_id, document = self.approved_match()

        class FakeExtractor:
            def extract(self, path):
                return {
                    "screen_type": "match_facts",
                    "records": [{"type": "match", "home_goals": 99}],
                    "evidence": {},
                    "issues": ["Synthetic bad OCR"],
                }

        result = extract_pending(self.store, self.root, {73}, extractor=FakeExtractor())
        self.assertEqual(result["extracted"], 1)
        self.assertEqual(self.store.find("matches")["home_goals"], 1)
        result = extract_pending(self.store, self.root, {73}, extractor=FakeExtractor())
        self.assertEqual(result["skipped"], 1)
        review = make_review(self.store, {73})
        self.assertEqual(review["sources"][0]["records"][0]["home_goals"], 1)

    def test_new_non_match_layouts_refresh_once_without_touching_reviewed_stats(self):
        match_source, document = self.approved_match()
        transfer_source = self.prepare_source(1124, "black")
        transfer = {
            "type": "player_transfer",
            "player": "Test Player",
            "to_club": "Notts County",
            "transfer_type": "permanent",
            "date_basis": "Year unknown",
            "contract_months": 24,
        }
        approve_review(
            self.store,
            self.review(transfer_source, [transfer]),
            "Reviewed signing",
        )
        for source_id, screen_type in (
            (match_source, "match_facts"),
            (transfer_source, "transfer"),
        ):
            self.store.update("source_images", source_id, {"screen_type": screen_type})
            self.store.insert(
                "extractions",
                {
                    "source_id": source_id,
                    "extractor_version": "1.1.0",
                    "candidate_json": "[]",
                    "evidence_json": "{}",
                    "issues_json": "[]",
                },
            )
        before = self.store.find("player_transfers")
        reviewed = sorted(self.store.rows("reviews"), key=lambda row: row["id"])
        extractor = Mock()
        extractor.extract.return_value = {
            "screen_type": "transfer",
            "records": [{**transfer, "contract_months": 99}],
            "evidence": {},
            "issues": [],
        }
        result = extract_pending(self.store, self.root, extractor=extractor)
        self.assertEqual((result["extracted"], result["skipped"]), (1, 1))
        self.assertEqual(result["processed_source_ids"], [transfer_source])
        self.assertEqual(
            self.store.find("player_transfers"),
            before,
        )
        self.assertEqual(
            sorted(self.store.rows("reviews"), key=lambda row: row["id"]),
            reviewed,
        )
        self.assertEqual(
            self.store.get("extractions", transfer_source)["extractor_version"],
            EXTRACTOR_VERSION,
        )
        self.assertEqual(
            self.store.get("extractions", match_source)["extractor_version"],
            "1.1.0",
        )
        second = extract_pending(self.store, self.root, extractor=extractor)
        self.assertEqual((second["extracted"], second["skipped"]), (0, 2))
        self.assertEqual(extractor.extract.call_count, 1)
        self.assertEqual(
            make_review(self.store, {1124})["sources"][0]["records"][0][
                "contract_months"
            ],
            24,
        )

    def test_failed_layout_refresh_retries_without_marking_it_current(self):
        source_id = self.prepare_source(328, "white")
        self.store.update("source_images", source_id, {"screen_type": "news"})
        self.store.insert(
            "extractions",
            {
                "source_id": source_id,
                "extractor_version": "1.1.0",
                "candidate_json": "[]",
                "evidence_json": "{}",
                "issues_json": "[]",
            },
        )
        extractor = Mock()
        extractor.extract.side_effect = [
            ValueError("OCR interrupted"),
            {"screen_type": "news", "records": [], "evidence": {}, "issues": []},
        ]
        self.assertEqual(
            extract_pending(self.store, self.root, extractor=extractor)["errors"],
            1,
        )
        self.assertEqual(
            self.store.find("extractions")["extractor_version"],
            "1.1.0",
        )
        self.assertEqual(
            extract_pending(self.store, self.root, extractor=extractor)["extracted"],
            1,
        )

    def test_only_dashboard_award_tiles_are_refreshed(self):
        award_source = self.prepare_source(823, "white")
        ordinary_source = self.prepare_source(824, "black")
        for source_id, text in (
            (
                award_source,
                "STANDINGS Williams grabs January Player of the Month Award",
            ),
            (ordinary_source, "Mr. Kedia STANDINGS TRANSFER HUB"),
        ):
            self.store.update("source_images", source_id, {"screen_type": "dashboard"})
            evidence = json.dumps({"full_image_tokens": [{"text": text}]})
            self.store.insert(
                "extractions",
                {
                    "source_id": source_id,
                    "extractor_version": "1.1.0",
                    "candidate_json": "[]",
                    "evidence_json": evidence,
                    "issues_json": "[]",
                },
            )
        extractor = Mock()
        extractor.extract.return_value = {
            "screen_type": "dashboard_award",
            "records": [],
            "evidence": {},
            "issues": [],
        }
        result = extract_pending(self.store, self.root, extractor=extractor)
        self.assertEqual(result["processed_source_ids"], [award_source])
        self.assertEqual((result["extracted"], result["skipped"]), (1, 1))

    def test_news_ocr_reuses_existing_player_and_imports_monthly_award_once(self):
        self.prepare_source(328, "white")
        player_id = self.create_player("Andy King")
        candidate = parse_news_event(
            "King grabs August Player of the Month Award",
            "King's impressive performance for Notts County earned him the EFL League Two award.",
            "2018-09-05",
        )
        extractor = Mock()
        extractor.extract.return_value = {
            "screen_type": "news",
            "records": [candidate],
            "evidence": {},
            "issues": [],
        }
        extract_pending(self.store, self.root, extractor=extractor)
        review = make_review(self.store, {328})
        record = review["sources"][0]["records"][0]
        self.assertEqual(
            (record["player"], record["player_id"]), ("Andy King", player_id)
        )
        self.assertEqual(
            self.store.count("competition_events"),
            0,
        )
        approve_review(self.store, review, "Checked monthly award")
        approve_review(self.store, review, "Repeat")
        self.assertEqual(self.store.count("players"), 1)
        self.assertEqual(
            tuple(
                self.store.find("competition_events")[field]
                for field in ("player_id", "period")
            ),
            (player_id, "2018-08"),
        )
        self.assertEqual(len(dashboard_data(self.store)["competition_events"]), 1)

    def test_news_ocr_does_not_choose_between_players_with_same_surname(self):
        self.prepare_source(328, "white")
        self.create_player("Andy King")
        self.create_player("Joshua King")
        candidate = parse_news_event(
            "King grabs August Player of the Month Award", announced_on="2018-09-05"
        )
        extractor = Mock()
        extractor.extract.return_value = {
            "screen_type": "news",
            "records": [candidate],
            "evidence": {},
            "issues": [],
        }
        extract_pending(self.store, self.root, extractor=extractor)
        source = make_review(self.store, {328})["sources"][0]
        self.assertNotIn("player_id", source["records"][0])
        self.assertEqual(source["records"][0]["player"], "King")
        self.assertTrue(
            any("Ambiguous OCR player" in issue for issue in source["issues"])
        )
        self.assertEqual(self.store.count("players"), 2)

    def test_refreshed_news_adds_new_awards_without_replacing_reviewed_values(self):
        source_id = self.prepare_source(1053, "white")
        reviewed = {
            "type": "competition_event",
            "event_type": "goalkeeper_of_the_competition",
            "player": "Aaron Ramsdale",
            "club": "Notts County",
            "competition": "EFL League Two",
            "season": "2018/19",
            "period": "2018/19",
            "announced_on": "2019-05-04",
            "description": "Reviewed award",
        }
        approve_review(
            self.store,
            self.review(source_id, [reviewed]),
            "Existing checked award",
        )
        before = self.store.find("competition_events")
        news = {**reviewed, "description": "Fresh OCR wording"}
        champion = {
            "type": "competition_event",
            "event_type": "champion",
            "club": "Notts County",
            "competition": "EFL League Two",
            "season": "2018/19",
            "period": "2018/19",
            "announced_on": "2019-05-04",
            "description": "Notts County Crowned EFL League Two Champions",
        }
        extractor = Mock()
        extractor.extract.return_value = {
            "screen_type": "news",
            "records": [news, champion],
            "evidence": {},
            "issues": [],
        }
        extract_pending(self.store, self.root, extractor=extractor)
        source = make_review(self.store, {1053})["sources"][0]
        self.assertEqual(len(source["records"]), 2)
        self.assertEqual(source["records"][0]["description"], "Reviewed award")
        self.assertEqual(source["records"][1]["event_type"], "champion")
        self.assertFalse(source["complete"])
        self.assertEqual(
            self.store.find("competition_events"),
            before,
        )

    def test_new_transfer_ocr_proposes_unknown_wage_without_changing_saved_contract(
        self,
    ):
        source_id = self.prepare_source(1124, "white")
        transfer = {
            "type": "player_transfer",
            "player": "Matty James",
            "to_club": "Notts County",
            "transfer_type": "permanent",
            "date_basis": "Year unknown",
            "contract_months": 24,
            "weekly_wage_minor": None,
        }
        approve_review(
            self.store, self.review(source_id, [transfer]), "Reviewed signing"
        )
        extractor = Mock()
        extractor.extract.return_value = {
            "screen_type": "transfer",
            "records": [
                {**transfer, "weekly_wage_minor": 3599900, "contract_months": 99}
            ],
            "evidence": {},
            "issues": [],
        }
        extract_pending(self.store, self.root, extractor=extractor)
        source = make_review(self.store, {1124})["sources"][0]
        self.assertEqual(len(source["records"]), 1)
        self.assertEqual(source["records"][0]["weekly_wage_minor"], 3599900)
        self.assertEqual(source["records"][0]["contract_months"], 24)
        self.assertFalse(source["complete"])
        self.assertIsNone(self.store.find("player_transfers")["weekly_wage_minor"])

    def test_export_and_backup_preserve_canonical_data(self):
        self.approved_match()
        output = self.root / "exports" / "career.json"
        export_data(self.store, output)
        exported = json.loads(output.read_text())
        self.assertEqual(len(exported["matches"]), 1)
        self.assertIs(
            next(
                competition
                for competition in exported["competitions"]
                if competition["name"] == "European International Cup"
            )["is_preseason"],
            True,
        )
        backup = self.root / "backup.json"
        backup_records(self.store, backup)
        restored = Store.load(backup)
        self.assertEqual(restored.count("reviews"), 1)
        self.assertEqual(restored.rows("reviews"), self.store.rows("reviews"))
        self.assertEqual(validate_records(restored), [])
        with self.assertRaises(FileExistsError):
            backup_records(self.store, backup)

    def test_start_and_end_snapshots_are_distinct_and_partial_source_stays_queued(self):
        start_source = self.prepare_source(70, "white")
        end_source = self.prepare_source(1055, "black")
        base = {
            "type": "player_snapshot",
            "player": "Aaron Ramsdale",
            "season": "2018/19",
            "club": "Notts County",
            "date_precision": "season",
            "date_basis": "Boundary squad observation; day not visible",
        }
        start = {**base, "snapshot_kind": "season_start", "overall": 62}
        end = {**base, "snapshot_kind": "season_end", "overall": 65}
        approve_review(
            self.store,
            self.review(start_source, [start], complete=False),
            "Opening squad",
        )
        approve_review(
            self.store,
            self.review(end_source, [end], complete=False),
            "Closing squad",
        )
        self.assertEqual(status(self.store)["records"]["players"], 1)
        self.assertEqual(status(self.store)["records"]["player_snapshots"], 2)
        self.assertEqual(status(self.store)["source_states"], {"needs_review": 2})

    def test_explicit_correction_can_clear_unknown_values_and_restore_previous_value(
        self,
    ):
        source_id, document = self.approved_match()
        cleared = copy.deepcopy(document)
        cleared["sources"][0]["records"][0].update(home_goals=None, away_goals=None)
        approve_review(
            self.store,
            cleared,
            "Uncertain second reading should not overwrite known data",
        )
        self.assertEqual(self.store.find("matches")["home_goals"], 1)
        approve_review(
            self.store,
            cleared,
            "Withdraw the score after checking evidence",
            replace_reviewed=True,
        )
        self.assertIsNone(self.store.find("matches")["home_goals"])
        approve_review(
            self.store,
            document,
            "Restore the visually confirmed score",
            replace_reviewed=True,
        )
        self.assertEqual(self.store.find("matches")["home_goals"], 1)
        self.assertEqual(status(self.store)["records"]["matches"], 1)

    def test_export_uses_present_path_after_rename(self):
        self.approved_match()
        (self.raw / "Screenshot (73).png").rename(self.raw / "Screenshot (74).png")
        inventory(self.store, self.root)
        output = self.root / "career.json"
        export_data(self.store, output)
        source = json.loads(output.read_text())["source_images"][0]
        self.assertEqual(source["path"], "raw_screenshots/Screenshot (74).png")
        self.assertIs(source["available"], True)

    def test_non_match_records_are_repeatable_and_totals_keep_their_scope(self):
        source_id = self.prepare_source(1055, "white")
        totals = {
            "type": "player_competition_snapshot",
            "player": "Aaron Ramsdale",
            "club": "Notts County",
            "season": "2018/19",
            "scope": "all_competitions",
            "appearances": 53,
            "clean_sheets": 18,
        }
        award = {
            "type": "competition_event",
            "competition": "EFL League Two",
            "season": "2018/19",
            "player": "Aaron Ramsdale",
            "club": "Notts County",
            "event_type": "goalkeeper_of_the_competition",
            "announced_on": "2019-05-04",
            "description": "Visually checked tournament award",
        }
        loan = {
            "type": "player_transfer",
            "player": "Dominic Calvert-Lewin",
            "to_club": "Notts County",
            "transfer_type": "loan",
            "date_basis": "26/08 shown; year is unconfirmed",
            "fee_minor": None,
            "contract_months": 12,
            "loan_months": 24,
        }
        document = self.review(source_id, [totals, award, loan], complete=False)
        approve_review(self.store, document, "Synthetic reviewed non-match records")
        approve_review(self.store, document, "Repeat")
        self.assertIsNone(
            self.store.find("player_competition_snapshots")["competition_season_id"]
        )
        self.assertEqual(
            self.store.count("player_competition_snapshots"),
            1,
        )
        self.assertEqual(
            tuple(
                self.store.find("player_transfers")[field]
                for field in ("contract_months", "loan_months", "fee_minor")
            ),
            (12, 24, None),
        )

    def test_core_batch_never_imports_unreviewed_detailed_fields(self):
        match_source, document = self.approved_match()
        self.store.update("source_images", match_source, {"screen_type": "match_facts"})
        self.prepare_source(76, "black")

        class FakePlayerExtractor:
            def extract(self, path):
                return {
                    "screen_type": "player_performance",
                    "evidence": {},
                    "issues": [],
                    "records": [
                        {
                            "type": "player_match",
                            "player": "Takefusa Kubo",
                            "club": "Notts County",
                            "overall": 63,
                            "rating": 8.4,
                            "goals": 0,
                            "assists": 1,
                            "passes_completed_short": 999,
                            "clearances": 999,
                        }
                    ],
                }

        extract_pending(self.store, self.root, {76}, extractor=FakePlayerExtractor())
        decisions = {"player_core_ranges": [[76, 76]]}
        review = prepare_player_cores(self.store, decisions)
        record = review["sources"][0]["records"][0]
        self.assertNotIn("clearances", record)
        self.assertNotIn("passes_completed_short", record)
        self.assertFalse(review["sources"][0]["complete"])
        approve_review(self.store, review, "Only image-reviewed core fields")
        self.assertIsNone(self.store.find("player_matches")["clearances"])
        self.assertEqual(
            self.store.find("player_matches")["assists"],
            1,
        )

    def test_player_review_restores_detailed_candidates_without_overwriting_core_corrections(
        self,
    ):
        match_source, document = self.approved_match()
        player_source = self.prepare_source(76, "black")
        extractor = Mock()
        extractor.extract.return_value = {
            "screen_type": "player_performance",
            "evidence": {},
            "issues": [],
            "records": [
                {
                    "type": "player_match",
                    "player": "Kubo OCR",
                    "club": "Wrong OCR club",
                    "match_id": None,
                    "goals": 9,
                    "assists": 8,
                    "key_passes": 3,
                    "interceptions": 4,
                    "passes_completed_short": 15,
                }
            ],
        }
        extract_pending(self.store, self.root, {76}, extractor=extractor)
        reviewed = {
            "type": "player_match",
            "player": "Takefusa Kubo",
            "club": "Notts County",
            "match_id": self.match_id,
            "goals": 0,
            "assists": 1,
            "key_passes": 2,
            "interceptions": None,
        }
        approve_review(
            self.store,
            self.review(player_source, [reviewed]),
            "Corrected core fields",
        )

        source = make_review(self.store, {76})["sources"][0]
        record = source["records"][0]

        self.assertEqual(record["player"], "Takefusa Kubo")
        self.assertEqual(record["club"], "Notts County")
        self.assertEqual(record["match_id"], self.match_id)
        self.assertEqual(
            (record["goals"], record["assists"], record["key_passes"]), (0, 1, 2)
        )
        self.assertEqual(record["interceptions"], 4)
        self.assertEqual(record["passes_completed_short"], 15)
        self.assertFalse(source["complete"])
        self.assertTrue(
            any("Unreviewed player fields" in issue for issue in source["issues"])
        )
        self.assertIsNone(self.store.find("player_matches")["interceptions"])
        approve_review(
            self.store,
            {"schema_version": 3, "sources": [source]},
            "Detailed fields checked",
        )
        saved = self.store.find("player_matches")
        self.assertEqual(
            tuple(
                saved[field]
                for field in (
                    "goals",
                    "assists",
                    "key_passes",
                    "interceptions",
                    "passes_completed_short",
                )
            ),
            (0, 1, 2, 4, 15),
        )

    def test_refreshed_team_fields_fill_blanks_without_replacing_saved_match_values(
        self,
    ):
        source_id, document = self.approved_match()
        extractor = Mock()
        extractor.extract.return_value = {
            "screen_type": "match_facts",
            "evidence": {},
            "issues": [],
            "records": [
                {
                    **self.match_record(),
                    "home_club": "Incorrect OCR club",
                    "home_goals": 9,
                    "team_stats": {
                        "home": {"shots": 99, "corners": 1},
                        "away": {"fouls": 8, "corners": 2},
                    },
                }
            ],
        }
        extract_pending(
            self.store, self.root, {73}, reextract=True, extractor=extractor
        )

        source = make_review(self.store, {73})["sources"][0]

        self.assertFalse(source["complete"])
        self.assertEqual(source["records"][0]["home_club"], "Notts County")
        self.assertEqual(source["records"][0]["home_goals"], 1)
        self.assertEqual(
            source["records"][0]["team_stats"],
            {"home": {"shots": 6, "corners": 1}, "away": {"fouls": 0, "corners": 2}},
        )
        result = import_pending(self.store, {73}, {source_id})
        self.assertEqual(result["imported_sources"], 1)
        self.assertEqual(result["skipped_sources"], [])
        home = self.store.find("team_matches", club_id=self.home_club_id)
        away = next(
            row
            for row in self.store.rows("team_matches")
            if row["club_id"] != self.home_club_id
        )
        self.assertEqual((home["shots"], home["corners"]), (6, 1))
        self.assertEqual((away["fouls"], away["corners"]), (0, 2))
        self.assertEqual(
            self.store.find("matches")["id"],
            self.match_id,
        )
        self.assertEqual(
            import_pending(self.store, {73}, {source_id})["imported_sources"], 0
        )

    def test_fixture_context_rejects_interrupted_player_groups(self):
        source_id, document = self.approved_match()
        self.store.update("source_images", source_id, {"screen_type": "match_facts"})
        interruption = self.prepare_source(74, "gray")
        player_source = self.prepare_source(75, "black")
        self.store.update("source_images", interruption, {"screen_type": "squad"})
        self.store.update(
            "source_images", player_source, {"screen_type": "player_performance"}
        )
        with self.assertRaisesRegex(ValueError, "boundary"):
            fixture_contexts(self.store)

    def test_goalkeeper_shootout_counts_remain_separate(self):
        source_id, document = self.approved_match()
        self.update_records("matches", {"home_penalties": 2, "away_penalties": 4})
        self.store.update("source_images", source_id, {"screen_type": "match_facts"})
        self.prepare_source(76, "black")

        class FakeKeeperExtractor:
            def extract(self, path):
                return {
                    "screen_type": "goalkeeper_performance",
                    "evidence": {},
                    "issues": [],
                    "records": [
                        {
                            "type": "player_match",
                            "player": "Aaron Ramsdale",
                            "club": "Notts County",
                            "rating": 6.8,
                            "overall": 63,
                            "goals_conceded": 5,
                            "assists": None,
                        }
                    ],
                }

        extract_pending(self.store, self.root, {76}, extractor=FakeKeeperExtractor())
        review = prepare_player_cores(
            self.store,
            {"player_core_ranges": [[76, 76]], "goalkeeper_zero_assists": [76]},
        )
        approve_review(self.store, review, "Verified match score and goalkeeper count")
        result = self.store.find("player_matches")
        self.assertEqual(
            (result["goals_conceded"], result["goals_conceded_displayed"]), (1, 5)
        )

    def test_coverage_assumes_opponent_own_goals_without_modifying_records(self):
        self.approved_match()
        self.update_records("matches", {"home_goals": 3, "away_goals": 2})
        player_id = self.create_player("Takefusa Kubo")
        insert_entity(
            self.store,
            "player_matches",
            {
                "match_id": self.match_id,
                "player_id": player_id,
                "club_id": self.home_club_id,
                "displayed_position": "CAM",
                "goals": 2,
                "assists": 1,
                "rating": 8.4,
                "overall": 63,
                "shots_on_target": 1,
                "shots_off_target": 0,
            },
        )
        report = coverage_report(self.store)
        self.assertEqual(report["summary"]["matches"], 1)
        self.assertEqual(report["summary"]["preseason_matches"], 1)
        self.assertEqual(report["summary"]["player_records"], 1)
        self.assertEqual(report["summary"]["matches_with_two_complete_team_rows"], 0)
        self.assertEqual(
            report["player_field_availability"]["minutes_played"],
            {"recorded": 0, "null": 1},
        )
        self.assertNotIn(
            "player_goal_difference",
            [warning["code"] for warning in report["warnings"]],
        )
        self.assertEqual(report["matches"][0]["goal_difference"], 1)
        self.assertEqual(report["matches"][0]["assumed_own_goals"], 1)
        self.assertEqual(report["summary"]["assumed_own_goals"], 1)
        self.assertEqual(self.store.find("matches")["home_goals"], 3)
        self.assertEqual(self.store.find("player_matches")["goals"], 2)

    def test_coverage_warns_when_player_goals_exceed_team_score(self):
        self.approved_match()
        player_id = self.create_player("Takefusa Kubo")
        insert_entity(
            self.store,
            "player_matches",
            {
                "match_id": self.match_id,
                "player_id": player_id,
                "club_id": self.home_club_id,
                "displayed_position": "CAM",
                "goals": 2,
            },
        )
        report = coverage_report(self.store)

        discrepancy = next(
            warning
            for warning in report["warnings"]
            if warning["code"] == "player_goal_difference"
        )
        self.assertEqual(discrepancy["difference"], -1)
        self.assertEqual(report["matches"][0]["assumed_own_goals"], 0)
        self.assertEqual(self.store.find("matches")["home_goals"], 1)
        self.assertEqual(self.store.find("player_matches")["goals"], 2)

    def test_coverage_does_not_assume_own_goals_with_unknown_player_goals(self):
        self.approved_match()
        player_id = self.create_player("Takefusa Kubo")
        insert_entity(
            self.store,
            "player_matches",
            {
                "match_id": self.match_id,
                "player_id": player_id,
                "club_id": self.home_club_id,
                "displayed_position": "CAM",
                "goals": None,
            },
        )
        report = coverage_report(self.store)

        self.assertIsNone(report["matches"][0]["credited_player_goals"])
        self.assertIsNone(report["matches"][0]["assumed_own_goals"])
        self.assertIn(
            "missing_player_core_fields",
            [warning["code"] for warning in report["warnings"]],
        )

    def test_coverage_warnings_identify_fixtures_and_missing_statistics(self):
        self.approved_match()
        player_id = self.create_player("Aaron Ramsdale")
        insert_entity(
            self.store,
            "player_matches",
            {
                "match_id": self.match_id,
                "player_id": player_id,
                "club_id": self.home_club_id,
                "displayed_position": "GK",
                "goals_conceded": 1,
                "shots_caught": 2,
                "shots_parried": 0,
                "rating": 6.5,
                "overall": 65,
                "assists": None,
            },
        )
        self.update_records(
            "team_matches",
            {
                "shots": 3,
                "shots_on_target": 2,
                "possession_pct": 50,
                "tackles": 1,
                "fouls": 0,
                "corners": None,
                "shot_accuracy_pct": 67,
                "pass_accuracy_pct": 80,
            },
            match_id=self.match_id,
        )

        report = coverage_report(self.store)

        warnings = {warning["code"]: warning for warning in report["warnings"]}
        self.assertEqual(
            warnings["missing_player_core_fields"]["fields"], {"assists": 1}
        )
        self.assertEqual(
            warnings["missing_player_core_fields"]["detail"],
            "Missing player stats: Aaron Ramsdale (assists).",
        )
        self.assertEqual(
            warnings["incomplete_team_statistics"]["detail"],
            "Missing team stats: Notts County (corners); Dundee FC (corners).",
        )
        for warning in report["warnings"]:
            self.assertEqual(warning["played_on"], "2018-07-04")
            self.assertEqual(warning["home_club"], "Notts County")
            self.assertEqual(warning["away_club"], "Dundee FC")
            self.assertEqual(warning["competition"], "European International Cup")
            self.assertTrue(warning["title"])
            self.assertTrue(warning["detail"])

    def test_coverage_does_not_treat_unknown_scores_as_draws(self):
        source_id, document = self.approved_match()
        self.update_records("matches", {"home_goals": None, "away_goals": None})
        report = coverage_report(self.store)
        self.assertEqual(report["competitions"][0]["known_results"], 0)
        self.assertEqual(report["competitions"][0]["draws"], 0)
        self.assertIsNone(report["matches"][0]["goal_difference"])
        self.assertIsNone(report["matches"][0]["assumed_own_goals"])
        self.assertIn(
            "missing_match_score", [warning["code"] for warning in report["warnings"]]
        )


class AutomaticImportTests(RecordTestCase):
    def setUp(self):
        super().setUp()
        self.match = {
            "type": "match",
            "season": "2018/19",
            "competition": "European International Cup",
            "played_on": "2018-07-04",
            "home_club": "Notts County",
            "away_club": "Dundee FC",
            "home_goals": 1,
            "away_goals": 1,
        }
        self.player = {
            "type": "player_match",
            "player": "Harry Kewell",
            "club": "Notts County",
            "match_id": None,
            "rating": 7.5,
            "goals": 1,
            "assists": 0,
        }

    def extract(self, *screens):
        for index in range(len(screens)):
            self.create_image(
                f"Screenshot ({73 + index}).png", color=(index * 20, 0, 0)
            )
        inventory(self.store, self.root)
        extractor = Mock()
        extractor.extract.side_effect = [
            {
                "screen_type": screen_type,
                "records": records,
                "evidence": {},
                "issues": [],
            }
            for screen_type, records in screens
        ]
        extract_pending(self.store, self.root, extractor=extractor)

    def test_opening_profile_uses_following_season_without_inventing_a_date(self):
        self.extract(
            (
                "squad",
                [
                    {
                        "type": "player_snapshot",
                        "player": "Harry Kewell",
                        "club": "Notts County",
                        "season": None,
                        "overall": 65,
                        "snapshot_kind": "first_observed",
                        "date_precision": "unknown",
                        "observed_on": None,
                    }
                ],
            ),
            ("match_facts", [self.match]),
        )

        result = import_pending(self.store)

        self.assertEqual(result["skipped_sources"], [])
        self.assertEqual(result["imported_sources"], 2)
        snapshot = self.store.find("player_snapshots")
        self.assertEqual(
            self.store.get("seasons", snapshot["season_id"])["label"], "2018/19"
        )
        self.assertIsNone(snapshot["observed_on"])
        self.assertIn("context", snapshot["date_basis"].lower())

    def test_season_tables_resolve_context_across_a_season_change(self):
        self.extract(
            ("match_facts", [{**self.match, "competition": "EFL League Two"}]),
            (
                "squad",
                [
                    {
                        "type": "player_competition_snapshot",
                        "player": "Harry Kewell",
                        "club": "Notts County",
                        "season": None,
                        "competition": "EFL League Two",
                        "scope": "competition",
                        "snapshot_kind": "in_season",
                        "appearances": 12,
                    }
                ],
            ),
            (
                "match_facts",
                [
                    {
                        **self.match,
                        "competition": "EFL League One",
                        "season": "2019/20",
                        "played_on": "2019-07-04",
                    }
                ],
            ),
        )

        result = import_pending(self.store)

        self.assertEqual(result["skipped_sources"], [])
        snapshot = self.store.find("player_competition_snapshots")
        self.assertEqual(
            self.store.get("seasons", snapshot["season_id"])["label"], "2018/19"
        )
        self.assertIsNone(snapshot["observed_on"])
        self.assertEqual(snapshot["appearances"], 12)

    def test_boundary_screens_resolve_via_named_competitions(self):
        totals = [
            {
                "type": "player_competition_snapshot",
                "player": "Harry Kewell",
                "club": "Notts County",
                "season": None,
                "competition": competition,
                "scope": "competition",
                "snapshot_kind": "in_season",
                "appearances": 0,
            }
            for competition in (
                "European International Cup",
                "EFL Championship",
            )
        ]
        self.extract(
            (
                "match_facts",
                [
                    {
                        **self.match,
                        "competition": "EFL Championship",
                        "season": "2020/21",
                        "played_on": "2021-04-10",
                    }
                ],
            ),
            (
                "match_facts",
                [
                    {
                        **self.match,
                        "season": "2020/21",
                        "played_on": "2020-07-15",
                    }
                ],
            ),
            ("squad", totals),
            (
                "squad",
                [
                    {
                        "type": "player_snapshot",
                        "player": "Harry Kewell",
                        "club": "Notts County",
                        "season": None,
                        "overall": 65,
                        "snapshot_kind": "first_observed",
                        "date_precision": "unknown",
                    }
                ],
            ),
            (
                "league_table",
                [
                    {
                        "type": "competition_event",
                        "event_type": "league_table_position",
                        "club": "Notts County",
                        "competition": "EFL Championship",
                        "season": None,
                        "period": "4",
                        "description": "Notts County finished 4th",
                    }
                ],
            ),
            (
                "match_facts",
                [
                    {
                        **self.match,
                        "season": "2021/22",
                        "played_on": "2021-07-20",
                    }
                ],
            ),
        )

        result = import_pending(self.store)

        self.assertEqual(result["skipped_sources"], [])
        self.assertEqual(result["imported_sources"], 6)
        for snapshot in self.store.rows("player_competition_snapshots"):
            self.assertEqual(
                self.store.get("seasons", snapshot["season_id"])["label"], "2020/21"
            )
        self.assertEqual(
            self.store.get("seasons", self.store.find("player_snapshots")["season_id"])[
                "label"
            ],
            "2020/21",
        )
        table = self.store.find(
            "competition_events", event_type="league_table_position"
        )
        self.assertEqual(
            self.store.get("competition_seasons", table["competition_season_id"])[
                "competition_id"
            ],
            self.store.find("competitions", name="EFL Championship")["id"],
        )

    def test_ambiguous_season_boundary_is_not_guessed(self):
        self.extract(
            ("match_facts", [self.match]),
            (
                "squad",
                [
                    {
                        "type": "player_snapshot",
                        "player": "Harry Kewell",
                        "club": "Notts County",
                        "season": None,
                        "overall": 65,
                        "snapshot_kind": "first_observed",
                    }
                ],
            ),
            (
                "match_facts",
                [{**self.match, "season": "2019/20", "played_on": "2019-07-04"}],
            ),
        )

        result = import_pending(self.store)

        self.assertEqual(result["imported_sources"], 2)
        self.assertEqual(len(result["skipped_sources"]), 1)
        self.assertIn("season", result["skipped_sources"][0]["reason"])
        self.assertEqual(
            self.store.count("player_snapshots"),
            0,
        )

    def test_annual_awards_include_our_players_and_outside_winners_without_league_links(
        self,
    ):
        self.extract(
            ("match_facts", [self.match]),
            ("player_performance", [self.player]),
            (
                "dashboard_award",
                [
                    parse_news_event(
                        "Harry Kewell wins Player of the Year", observed_on="2018-12-01"
                    )
                ],
            ),
            (
                "dashboard_award",
                [
                    parse_news_event(
                        "Player of the Year Announced Lionel Messi",
                        observed_on="2019-12-01",
                    )
                ],
            ),
        )

        result = import_pending(self.store)

        self.assertEqual(result["skipped_sources"], [])
        self.assertEqual(result["imported_sources"], 4)
        awards = [
            {**row, "name": self.store.get("players", row["player_id"])["name"]}
            for row in sorted(
                self.store.rows("competition_events"), key=lambda row: row["period"]
            )
        ]
        self.assertEqual(
            [(award["name"], award["period"]) for award in awards],
            [("Harry Kewell", "2018"), ("Lionel Messi", "2019")],
        )
        for award in awards:
            self.assertTrue(is_uuid(award["id"]))
            self.assertTrue(is_uuid(award["player_id"]))
            self.assertIsNone(award["competition_season_id"])
            self.assertIsNone(award["club_id"])
            self.assertIsNone(award["announced_on"])
        self.assertEqual(self.store.count("players"), 2)
        self.assertEqual(
            self.store.count("player_matches"),
            1,
        )
        self.assertEqual(
            self.store.count("competition_seasons"),
            1,
        )
        self.assertEqual(len(dashboard_data(self.store)["competition_events"]), 2)
        self.assertEqual(validate_records(self.store), [])

    def test_duplicate_annual_awards_keep_one_event_and_both_source_reviews(self):
        self.extract(
            (
                "news",
                [
                    parse_news_event(
                        "Lionel Messi wins Player of the Year",
                        announced_on="2019-12-12",
                    )
                ],
            ),
            (
                "dashboard_award",
                [
                    parse_news_event(
                        "Player of the Year Announced Lionel Messi",
                        observed_on="2019-12-01",
                    )
                ],
            ),
        )

        result = import_pending(self.store)

        self.assertEqual(result["skipped_sources"], [])
        self.assertEqual(result["imported_sources"], 2)
        self.assertEqual(
            self.store.count("competition_events"),
            1,
        )
        self.assertEqual(self.store.count("reviews"), 2)
        event = self.store.find("competition_events")
        self.assertEqual(event["announced_on"], "2019-12-12")
        self.assertEqual(import_pending(self.store)["imported_sources"], 0)
        self.assertEqual(
            self.store.find("competition_events"),
            event,
        )

    def test_conflicting_annual_winners_do_not_replace_the_saved_winner(self):
        self.extract(
            (
                "dashboard_award",
                [
                    parse_news_event(
                        "Lionel Messi wins Player of the Year", observed_on="2019-12-01"
                    )
                ],
            ),
            (
                "dashboard_award",
                [
                    parse_news_event(
                        "Cristiano Ronaldo wins Player of the Year",
                        observed_on="2019-12-01",
                    )
                ],
            ),
        )

        result = import_pending(self.store)

        self.assertEqual(result["imported_sources"], 1)
        self.assertEqual(len(result["skipped_sources"]), 1)
        self.assertIn("Conflict", result["skipped_sources"][0]["reason"])
        self.assertEqual(
            self.store.find("players")["name"],
            "Lionel Messi",
        )
        self.assertEqual(self.store.count("players"), 1)

    def test_annual_awards_never_borrow_a_year_from_neighboring_fixtures(self):
        self.extract(
            ("match_facts", [self.match]),
            (
                "dashboard_award",
                [parse_news_event("Player of the Year Announced Lionel Messi")],
            ),
        )

        result = import_pending(self.store)

        self.assertEqual(result["imported_sources"], 1)
        self.assertEqual(len(result["skipped_sources"]), 1)
        self.assertIn("calendar award year", result["skipped_sources"][0]["reason"])
        self.assertEqual(
            self.store.count("competition_events"),
            0,
        )

    def test_annual_awards_require_a_winner_and_year_without_a_competition_season(self):
        award = parse_news_event(
            "Lionel Messi wins Player of the Year", observed_on="2019-12-01"
        )
        self.extract(
            *(
                ("dashboard_award", [{**award, **invalid}])
                for invalid in (
                    {"player": None},
                    {"period": "2019/20"},
                    {"period": "December"},
                    {"competition": "EFL League One"},
                    {"season": "2019/20"},
                )
            )
        )

        result = import_pending(self.store)

        self.assertEqual(result["imported_sources"], 0)
        self.assertEqual(len(result["skipped_sources"]), 5)
        self.assertEqual(self.store.count("players"), 0)
        self.assertEqual(
            self.store.count("competition_events"),
            0,
        )

    def test_championship_captures_merge_but_seasons_and_competitions_stay_distinct(
        self,
    ):
        self.extract(
            (
                "news",
                [
                    parse_news_event(
                        "Notts County Crowned EFL League Two Champions",
                        announced_on="2019-05-04",
                    )
                ],
            ),
            (
                "dashboard_award",
                [
                    parse_news_event(
                        "Notts County Crowned EFL League Two Champions",
                        observed_on="2019-05-01",
                    )
                ],
            ),
            (
                "dashboard_award",
                [
                    parse_news_event(
                        "Notts County Crowned EFL League Two Champions",
                        observed_on="2020-05-01",
                    )
                ],
            ),
            (
                "dashboard_award",
                [
                    parse_news_event(
                        "Ipswich Crowned EFL League One Champions",
                        observed_on="2019-05-01",
                    )
                ],
            ),
        )

        result = import_pending(self.store)

        self.assertEqual(result["skipped_sources"], [])
        self.assertEqual(result["imported_sources"], 4)
        self.assertEqual(
            self.store.count("competition_events"),
            3,
        )
        self.assertEqual(self.store.count("reviews"), 4)
        dated = next(
            row
            for row in self.store.rows("competition_events")
            if row["announced_on"] is not None
        )
        self.assertEqual(dated["announced_on"], "2019-05-04")
        self.assertEqual(dated["period"], "2018/19")
        self.assertEqual(validate_records(self.store), [])

    def test_conflicting_champions_do_not_replace_the_saved_club(self):
        self.extract(
            (
                "dashboard_award",
                [
                    parse_news_event(
                        "Notts County Crowned EFL League Two Champions",
                        observed_on="2019-05-01",
                    )
                ],
            ),
            (
                "dashboard_award",
                [
                    parse_news_event(
                        "MK Dons Crowned EFL League Two Champions",
                        observed_on="2019-05-01",
                    )
                ],
            ),
        )

        result = import_pending(self.store)

        self.assertEqual(result["imported_sources"], 1)
        self.assertEqual(len(result["skipped_sources"]), 1)
        self.assertIn("Conflict", result["skipped_sources"][0]["reason"])
        winner = self.store.get(
            "clubs", self.store.find("competition_events")["club_id"]
        )["name"]
        self.assertEqual(winner, "Notts County")

    def test_news_assist_total_uses_unique_preceding_league_not_nearby_cup(self):
        self.extract(
            ("match_facts", [{**self.match, "competition": "EFL League Two"}]),
            ("player_performance", [self.player]),
            ("match_facts", [{**self.match, "played_on": "2018-07-05"}]),
            ("player_performance", [self.player]),
            (
                "news",
                [
                    {
                        "type": "player_competition_snapshot",
                        "player": "Kewell",
                        "club": "Notts County",
                        "competition_kind": "league",
                        "scope": "competition",
                        "snapshot_kind": "in_season",
                        "assists": 12,
                    }
                ],
            ),
        )

        result = import_pending(self.store)

        self.assertEqual(result["skipped_sources"], [])
        self.assertEqual(result["imported_sources"], 5)
        snapshot = self.store.find("player_competition_snapshots")
        edition = self.store.get(
            "competition_seasons", snapshot["competition_season_id"]
        )
        self.assertEqual(
            (
                self.store.get("players", snapshot["player_id"])["name"],
                self.store.get("competitions", edition["competition_id"])["name"],
                self.store.get("seasons", snapshot["season_id"])["label"],
                *(
                    snapshot[field]
                    for field in ("assists", "observed_on", "appearances", "goals")
                ),
            ),
            ("Harry Kewell", "EFL League Two", "2018/19", 12, None, None, None),
        )
        self.assertEqual(import_pending(self.store)["imported_sources"], 0)

    def test_news_assist_total_does_not_guess_between_leagues(self):
        self.extract(
            ("match_facts", [{**self.match, "competition": "EFL League Two"}]),
            ("player_performance", [self.player]),
            (
                "match_facts",
                [
                    {
                        **self.match,
                        "competition": "EFL League One",
                        "played_on": "2018-07-05",
                    }
                ],
            ),
            ("player_performance", [self.player]),
            (
                "news",
                [
                    {
                        "type": "player_competition_snapshot",
                        "player": "Kewell",
                        "club": "Notts County",
                        "competition_kind": "league",
                        "scope": "competition",
                        "snapshot_kind": "in_season",
                        "assists": 12,
                    }
                ],
            ),
        )

        result = import_pending(self.store)

        self.assertEqual(result["imported_sources"], 4)
        self.assertIn(
            "2 matching preceding league", result["skipped_sources"][0]["reason"]
        )
        self.assertEqual(
            self.store.count("player_competition_snapshots"),
            0,
        )

    def test_monthly_award_uses_player_league_in_award_month_not_nearby_cup(self):
        self.extract(
            ("match_facts", [{**self.match, "competition": "EFL League Two"}]),
            ("player_performance", [self.player]),
            ("match_facts", [{**self.match, "played_on": "2018-07-05"}]),
            ("player_performance", [self.player]),
            (
                "dashboard_award",
                [
                    parse_news_event(
                        "Kewell grabs July Player of the Month Award",
                        observed_on="2018-08-01",
                    )
                ],
            ),
        )

        result = import_pending(self.store)

        self.assertEqual(result["skipped_sources"], [])
        self.assertEqual(result["imported_sources"], 5)
        award = self.store.find("competition_events")
        edition = self.store.get("competition_seasons", award["competition_season_id"])
        self.assertEqual(
            (
                self.store.get("players", award["player_id"])["name"],
                self.store.get("competitions", edition["competition_id"])["name"],
                self.store.get("clubs", award["club_id"])["name"],
                award["period"],
                award["announced_on"],
            ),
            ("Harry Kewell", "EFL League Two", "Notts County", "2018-07", None),
        )
        self.assertEqual(self.store.count("players"), 1)
        payload = json.loads(
            self.store.latest_review(
                self.store.find("source_paths", sequence=77)["source_id"]
            )["payload_json"]
        )
        self.assertIn("2018-07", payload["records"][0]["context_basis"])
        self.assertEqual(import_pending(self.store)["imported_sources"], 0)

    def test_monthly_award_does_not_guess_between_leagues(self):
        self.extract(
            ("match_facts", [{**self.match, "competition": "EFL League Two"}]),
            ("player_performance", [self.player]),
            (
                "match_facts",
                [
                    {
                        **self.match,
                        "competition": "EFL League One",
                        "played_on": "2018-07-05",
                    }
                ],
            ),
            ("player_performance", [self.player]),
            (
                "news",
                [
                    parse_news_event(
                        "Kewell grabs July Player of the Month Award",
                        announced_on="2018-08-05",
                    )
                ],
            ),
        )

        result = import_pending(self.store)

        self.assertEqual(result["imported_sources"], 4)
        self.assertIn("2 matching league", result["skipped_sources"][0]["reason"])
        self.assertEqual(
            self.store.count("competition_events"),
            0,
        )

    def test_ambiguous_award_surname_does_not_create_another_player(self):
        self.create_player("Harry Kewell")
        self.create_player("Alan Kewell")
        self.extract(
            (
                "news",
                [
                    {
                        **parse_news_event(
                            "Kewell grabs July Player of the Month Award",
                            announced_on="2018-08-05",
                        ),
                        "competition": "EFL League Two",
                    }
                ],
            )
        )

        result = import_pending(self.store)

        self.assertEqual(result["imported_sources"], 0)
        self.assertIn("Ambiguous player name", result["skipped_sources"][0]["reason"])
        self.assertEqual(self.store.count("players"), 2)

    def test_golden_boot_uses_matching_championship_and_individual_award_context(self):
        self.extract(
            (
                "news",
                [
                    parse_news_event(
                        "Goalkeeper of the Tournament Announced",
                        "Harry Kewell has been named goalkeeper of the EFL League Two.",
                        "2019-05-04",
                    ),
                    parse_news_event(
                        "Notts County Crowned EFL League Two Champions",
                        announced_on="2019-05-04",
                    ),
                    parse_news_event(
                        "Another Forward Wins Golden Boot", announced_on="2019-05-04"
                    ),
                ],
            )
        )

        result = import_pending(self.store)

        self.assertEqual(result["skipped_sources"], [])
        self.assertEqual(result["imported_records"], 3)
        award = self.store.find("competition_events", event_type="golden_boot")
        edition = self.store.get("competition_seasons", award["competition_season_id"])
        self.assertEqual(
            self.store.get("competitions", edition["competition_id"])["name"],
            "EFL League Two",
        )
        self.assertIsNone(award["club_id"])

    def test_golden_boot_does_not_borrow_conflicting_news_context(self):
        self.extract(
            (
                "news",
                [
                    parse_news_event(
                        "Goalkeeper of the Tournament Announced",
                        "Harry Kewell has been named goalkeeper of the EFL League One.",
                        "2019-05-04",
                    ),
                    parse_news_event(
                        "Notts County Crowned EFL League Two Champions",
                        announced_on="2019-05-04",
                    ),
                    parse_news_event(
                        "Another Forward Wins Golden Boot", announced_on="2019-05-04"
                    ),
                ],
            )
        )

        result = import_pending(self.store)

        self.assertEqual(result["imported_sources"], 0)
        self.assertIn(
            "A competition is required for golden_boot",
            result["skipped_sources"][0]["reason"],
        )

    def test_golden_boot_does_not_borrow_awards_from_a_different_date(self):
        self.extract(
            (
                "news",
                [
                    parse_news_event(
                        "Goalkeeper of the Tournament Announced",
                        "Harry Kewell has been named goalkeeper of the EFL League Two.",
                        "2019-05-04",
                    ),
                    parse_news_event(
                        "Notts County Crowned EFL League Two Champions",
                        announced_on="2019-05-04",
                    ),
                    parse_news_event(
                        "Another Forward Wins Golden Boot", announced_on="2019-05-05"
                    ),
                ],
            )
        )

        result = import_pending(self.store)

        self.assertEqual(result["imported_sources"], 0)
        self.assertIn(
            "A competition is required for golden_boot",
            result["skipped_sources"][0]["reason"],
        )

    def test_repeated_name_consensus_resolves_same_club_ocr_variant(self):
        self.extract(
            ("match_facts", [self.match]),
            ("player_performance", [{**self.player, "player": "Harry KewellO"}]),
            ("match_facts", [{**self.match, "played_on": "2018-07-05"}]),
            ("player_performance", [self.player]),
            ("match_facts", [{**self.match, "played_on": "2018-07-06"}]),
            ("player_performance", [self.player]),
        )
        evidence = {
            "fields": {
                "first_name": {"raw_text": "Harry"},
                "last_name": {
                    "raw_text": "Kewell",
                    "initial_reading": {"raw_text": "KewellO"},
                    "method": "rapidocr_detected_name_consensus",
                },
            }
        }
        for sequence in (76, 78):
            self.store.update(
                "extractions",
                self.store.find("source_paths", sequence=sequence)["source_id"],
                {"evidence_json": json.dumps(evidence)},
            )

        result = import_pending(self.store)

        self.assertEqual(result["skipped_sources"], [])
        self.assertEqual(
            [row["name"] for row in self.store.rows("players")],
            ["Harry Kewell"],
        )
        self.assertEqual(
            self.store.count("player_matches"),
            3,
        )
        payload = json.loads(
            self.store.latest_review(
                self.store.find("source_paths", sequence=74)["source_id"]
            )["payload_json"]
        )
        self.assertIn("2 other screenshots", payload["records"][0]["context_basis"])

    def test_single_name_correction_does_not_establish_a_global_alias(self):
        self.extract(
            ("match_facts", [self.match]),
            ("player_performance", [{**self.player, "player": "Harry KewellO"}]),
            ("match_facts", [{**self.match, "played_on": "2018-07-05"}]),
            ("player_performance", [self.player]),
        )
        self.store.update(
            "extractions",
            self.store.find("source_paths", sequence=76)["source_id"],
            {
                "evidence_json": json.dumps(
                    {
                        "fields": {
                            "first_name": {"raw_text": "Harry"},
                            "last_name": {
                                "raw_text": "Kewell",
                                "initial_reading": {"raw_text": "KewellO"},
                                "method": "rapidocr_detected_name_consensus",
                            },
                        }
                    }
                )
            },
        )

        import_pending(self.store)

        self.assertEqual(
            {row["name"] for row in self.store.rows("players")},
            {"Harry Kewell", "Harry KewellO"},
        )

    def test_cached_candidates_import_and_link_once(self):
        self.extract(
            ("match_facts", [self.match]), ("player_performance", [self.player])
        )

        result = import_pending(self.store)

        self.assertEqual(result["imported_sources"], 2)
        self.assertEqual(result["imported_records"], 2)
        self.assertEqual(result["skipped_sources"], [])
        match_id = self.store.find("matches")["id"]
        self.assertEqual(
            self.store.find("player_matches")["match_id"],
            match_id,
        )
        self.assertEqual(status(self.store)["source_states"], {"imported": 2})
        self.assertEqual(import_pending(self.store)["imported_sources"], 0)
        self.assertEqual(self.store.count("reviews"), 2)
        self.assertEqual(validate_records(self.store), [])

    def test_interrupted_context_does_not_block_later_match(self):
        self.extract(
            ("match_facts", [self.match]),
            ("dashboard", []),
            ("player_performance", [self.player]),
            ("match_facts", [{**self.match, "played_on": "2018-07-05"}]),
            ("player_performance", [self.player]),
        )

        result = import_pending(self.store)

        self.assertEqual(result["imported_sources"], 3)
        self.assertEqual(len(result["skipped_sources"]), 1)
        self.assertEqual(len(result["ignored_sources"]), 1)
        self.assertIn(
            "No unambiguous preceding match", result["skipped_sources"][0]["reason"]
        )
        appearance_dates = [
            self.store.get("matches", row["match_id"])["played_on"]
            for row in self.store.rows("player_matches")
        ]
        self.assertEqual(appearance_dates, ["2018-07-05"])

    def test_invalid_match_cannot_reuse_previous_fixture(self):
        self.extract(
            ("match_facts", [self.match]),
            ("match_facts", [{**self.match, "played_on": None}]),
            ("player_performance", [self.player]),
        )

        result = import_pending(self.store)

        self.assertEqual(result["imported_sources"], 1)
        self.assertEqual(len(result["skipped_sources"]), 2)
        self.assertEqual(
            self.store.count("player_matches"),
            0,
        )
        self.assertEqual(validate_records(self.store), [])

    def test_selection_uses_existing_header_outside_selection(self):
        self.extract(
            ("match_facts", [self.match]), ("player_performance", [self.player])
        )
        self.assertEqual(import_pending(self.store, {73})["imported_sources"], 1)

        result = import_pending(self.store, {74})

        self.assertEqual(result["imported_sources"], 1)
        self.assertEqual(result["skipped_sources"], [])
        self.assertEqual(
            self.store.count("player_matches"),
            1,
        )

    def test_refresh_preserves_saved_values(self):
        self.extract(
            ("match_facts", [self.match]), ("player_performance", [self.player])
        )
        import_pending(self.store)
        source_id = self.store.find("source_paths", sequence=74)["source_id"]
        self.store.update(
            "extractions",
            source_id,
            {"candidate_json": json.dumps([{**self.player, "goals": 5}])},
        )

        result = import_pending(self.store, refreshed_source_ids={source_id})

        self.assertEqual(result["imported_sources"], 0)
        self.assertEqual(result["unchanged_sources"], 1)
        self.assertEqual(self.store.find("player_matches")["goals"], 1)
        self.assertEqual(self.store.count("reviews"), 2)

    def test_import_reuses_historical_player_and_club_corrections(self):
        raw_match = {**self.match, "home_club": "Notts Countv"}
        raw_player = {**self.player, "player": "Harry KewelI", "club": "Notts Countv"}
        self.extract(
            ("match_facts", [raw_match]),
            ("player_performance", [raw_player]),
            ("match_facts", [{**raw_match, "played_on": "2018-07-05"}]),
            ("player_performance", [raw_player]),
        )
        reviewed = make_review(self.store, {73, 74})
        reviewed["sources"][0]["records"] = [self.match]
        reviewed["sources"][1]["records"] = [
            {**self.player, "match_source_id": reviewed["sources"][0]["source_id"]}
        ]
        for source in reviewed["sources"]:
            source["complete"] = True
        approve_review(self.store, reviewed, "Historical name corrections")

        result = import_pending(self.store)

        self.assertEqual(result["imported_sources"], 2)
        self.assertEqual(result["skipped_sources"], [])
        self.assertEqual(self.store.count("players"), 1)
        self.assertEqual(self.store.count("clubs"), 2)
        self.assertEqual(self.store.count("matches"), 2)
        self.assertEqual(
            self.store.find("players")["name"],
            "Harry Kewell",
        )

    def test_outdated_missing_goalkeeper_counts_refresh_once(self):
        keeper = {
            **self.player,
            "player": "Aaron Ramsdale",
            "displayed_position": "GK",
            "assists": None,
            "goals_conceded": 1,
        }
        self.extract(
            ("match_facts", [self.match]), ("goalkeeper_performance", [keeper])
        )
        import_pending(self.store)
        source_id = self.store.find("source_paths", sequence=74)["source_id"]
        self.store.update(
            "extractions",
            source_id,
            {
                "extractor_version": "1.2.0",
                "evidence_json": json.dumps({"fields": {"assists": {"raw_text": "."}}}),
            },
        )
        extractor = Mock()
        extractor.extract.return_value = {
            "screen_type": "goalkeeper_performance",
            "records": [{**keeper, "assists": 0}],
            "evidence": {},
            "issues": [],
        }

        result = extract_pending(self.store, self.root, extractor=extractor)

        self.assertEqual(result["processed_source_ids"], [source_id])
        self.assertIsNone(self.store.find("player_matches")["assists"])
        import_pending(self.store, refreshed_source_ids=result["processed_source_ids"])
        self.assertEqual(
            self.store.find("player_matches")["assists"],
            0,
        )
        self.assertEqual(
            extract_pending(self.store, self.root, extractor=extractor)["extracted"],
            0,
        )
        extractor.extract.assert_called_once()

    def test_outdated_ocr_does_not_refresh_corrected_numeric_values(self):
        self.extract(
            ("match_facts", [self.match]), ("player_performance", [self.player])
        )
        import_pending(self.store)
        self.store.update(
            "extractions",
            self.store.find("source_paths", sequence=74)["source_id"],
            {
                "extractor_version": "1.2.0",
                "evidence_json": json.dumps({"fields": {"assists": {"raw_text": "."}}}),
            },
        )
        extractor = Mock()

        result = extract_pending(self.store, self.root, extractor=extractor)

        self.assertEqual(result["extracted"], 0)
        self.assertEqual(result["skipped"], 2)
        extractor.extract.assert_not_called()

    def test_goalkeeper_shootout_count_is_normalized_automatically(self):
        keeper = {
            **self.player,
            "player": "Aaron Ramsdale",
            "displayed_position": "GK",
            "goals": None,
            "goals_conceded": 4,
        }
        self.extract(
            ("match_facts", [{**self.match, "home_penalties": 5, "away_penalties": 3}]),
            ("goalkeeper_performance", [keeper]),
        )

        result = import_pending(self.store)

        self.assertEqual(result["skipped_sources"], [])
        appearance = self.store.find("player_matches")
        self.assertEqual(appearance["goals_conceded"], 1)
        self.assertEqual(appearance["goals_conceded_displayed"], 4)
        self.assertIn("shootout", appearance["goals_conceded_basis"])

    def test_ambiguous_goalkeeper_count_is_skipped(self):
        keeper = {**self.player, "displayed_position": "GK", "goals_conceded": 7}
        self.extract(
            ("match_facts", [{**self.match, "home_penalties": 5, "away_penalties": 3}]),
            ("goalkeeper_performance", [keeper]),
        )

        result = import_pending(self.store)

        self.assertEqual(result["imported_sources"], 1)
        self.assertEqual(len(result["skipped_sources"]), 1)
        self.assertIn("Ambiguous shootout", result["skipped_sources"][0]["reason"])
        self.assertEqual(
            self.store.count("player_matches"),
            0,
        )

    def test_complementary_transfer_panels_merge_into_one_signing(self):
        contract = {
            "type": "player_transfer",
            "player": "Federico Valverde",
            "transfer_type": "permanent",
            "to_club": "Notts County",
            "weekly_wage_minor": 9000000,
            "contract_months": 60,
            "date_basis": "01/07 shown in the agreed contract panel; year requires review.",
        }
        offer = {
            "type": "player_transfer",
            "player": "Federico Valverde",
            "transfer_type": "permanent",
            "to_club": "Notts County",
            "weekly_wage_minor": 9000000,
            "fee_minor": 1570000000,
            "date_basis": "01/07 shown in the selected offer row; year requires review.",
        }
        self.extract(
            ("match_facts", [self.match]),
            ("transfer", [contract]),
            ("transfer", [offer]),
        )

        result = import_pending(self.store)

        self.assertEqual(result["skipped_sources"], [])
        self.assertEqual(result["imported_sources"], 3)
        self.assertEqual(self.store.count("player_transfers"), 1)
        row = self.store.find("player_transfers")
        self.assertEqual(row["fee_minor"], 1570000000)
        self.assertEqual(row["weekly_wage_minor"], 9000000)
        self.assertEqual(row["contract_months"], 60)

    def test_undated_complementary_transfer_panels_merge(self):
        contract = {
            "type": "player_transfer",
            "player": "Federico Valverde",
            "transfer_type": "permanent",
            "to_club": "Notts County",
            "weekly_wage_minor": 9000000,
            "contract_months": 60,
            "date_basis": "01/07 shown in the agreed contract panel; year requires review.",
        }
        offer = {
            "type": "player_transfer",
            "player": "Federico Valverde",
            "transfer_type": "permanent",
            "to_club": "Notts County",
            "weekly_wage_minor": 9000000,
            "fee_minor": 1570000000,
            "date_basis": "01/07 shown in the selected offer row; year requires review.",
        }
        self.extract(("transfer", [contract]), ("transfer", [offer]))

        result = import_pending(self.store)

        self.assertEqual(result["skipped_sources"], [])
        self.assertEqual(self.store.count("player_transfers"), 1)
        row = self.store.find("player_transfers")
        self.assertEqual(row["fee_minor"], 1570000000)
        self.assertEqual(row["contract_months"], 60)

    def test_conflicting_transfer_panels_stay_separate_rows(self):
        first = {
            "type": "player_transfer",
            "player": "Federico Valverde",
            "transfer_type": "permanent",
            "to_club": "Notts County",
            "weekly_wage_minor": 9000000,
            "date_basis": "01/07 shown in the agreed contract panel; year requires review.",
        }
        second = {
            **first,
            "weekly_wage_minor": 12000000,
            "date_basis": "01/07 shown in the selected offer row; year requires review.",
        }
        self.extract(
            ("match_facts", [self.match]),
            ("transfer", [first]),
            ("transfer", [second]),
        )

        result = import_pending(self.store)

        self.assertEqual(result["skipped_sources"], [])
        self.assertEqual(self.store.count("player_transfers"), 2)

    def test_repeat_monthly_award_captures_merge_but_periods_stay_distinct(self):
        award = {
            "type": "competition_event",
            "event_type": "player_of_the_month",
            "player": "Harry Kewell",
            "competition": "European International Cup",
            "season": "2018/19",
            "period": "2018-08",
            "description": "Monthly award",
        }
        self.extract(
            ("news", [award]),
            ("news", [{**award, "description": "Repeated capture"}]),
            ("news", [{**award, "period": "2018-09"}]),
        )

        result = import_pending(self.store)

        self.assertEqual(result["skipped_sources"], [])
        self.assertEqual(result["imported_sources"], 3)
        self.assertEqual(self.store.count("competition_events"), 2)
        self.assertEqual(
            self.store.find("competition_events", period="2018-08")["description"],
            "Monthly award",
        )
        self.assertEqual(self.store.count("reviews"), 3)


class CommandTests(RecordTestCase):
    def setUp(self):
        super().setUp()
        self.diagnostics_path = self.root / "processing" / "data" / "diagnostics.json"
        self.store.save(self.diagnostics_path)
        self.record = {
            "type": "match",
            "season": "2018/19",
            "competition": "European International Cup",
            "played_on": "2018-07-04",
            "home_club": "Notts County",
            "away_club": "Dundee FC",
            "home_goals": 1,
            "away_goals": 1,
        }
        self.extractor = Mock()
        self.extractor.extract.return_value = {
            "screen_type": "match_facts",
            "records": [self.record],
            "evidence": {},
            "issues": [],
        }
        replacement = patch(
            "processing.extraction.ScreenshotExtractor", return_value=self.extractor
        )
        replacement.start()
        self.addCleanup(replacement.stop)

    def command(self, *arguments, expected_exit=0):
        from processing.__main__ import main

        self.store.save(self.diagnostics_path)
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                result = main(["--root", str(self.root), *map(str, arguments)])
            self.assertEqual(result, expected_exit, output.getvalue())
        finally:
            if self.diagnostics_path.is_file():
                self.store = Store.load(self.diagnostics_path)
        text = output.getvalue()
        return json.loads(text[text.index("{") :])

    def launcher(self, *arguments, python_exit=0):
        repository = Path(__file__).resolve().parents[2]
        bin_dir = self.root / "fake commands"
        bin_dir.mkdir(exist_ok=True)
        for name in ("npm", "python3"):
            executable = bin_dir / name
            script = '#!/bin/sh\nprintf "%s\\n" "$PWD" "$@"\n'
            if name == "python3":
                script += f"exit {python_exit}\n"
            executable.write_text(script, encoding="utf-8")
            executable.chmod(0o755)
        environment = {
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        }
        return subprocess.run(
            [str(repository / "run"), *arguments],
            cwd=self.root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=5,
        )

    def test_launcher_start_uses_port_5000_from_any_directory(self):
        repository = Path(__file__).resolve().parents[2]
        result = self.launcher("start", "--clearScreen", "false")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                str(repository),
                "--prefix",
                str(repository / "frontend"),
                "run",
                "dev",
                "--",
                "--port",
                "5000",
                "--strictPort",
                "--clearScreen",
                "false",
            ],
        )

    def test_launcher_start_does_not_run_processing(self):
        result = self.launcher("start")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("-m", result.stdout.splitlines())

    def test_process_recreates_default_data_directory_without_flags(self):
        image = self.create_image()
        image_bytes = image.read_bytes()
        data = self.root / "processing" / "data"
        for name in (
            "backups/old.json",
            "reviews/old.json",
            "previews/old.json",
            "cache.bin",
        ):
            stale = data / name
            stale.parent.mkdir(parents=True, exist_ok=True)
            stale.write_bytes(b"stale processing data")
        outside = self.root / "keep.txt"
        outside.write_text("not processing data", encoding="utf-8")
        extraction = self.extractor.extract.return_value

        def extract_after_reset(path):
            self.assertFalse((data / "backups").exists())
            self.assertFalse((data / "reviews").exists())
            self.assertFalse((data / "previews").exists())
            self.assertFalse((data / "cache.bin").exists())
            return extraction

        self.extractor.extract.side_effect = extract_after_reset
        identities = []
        for _attempt in range(2):
            result = self.command("process")
            self.assertEqual(result["extraction"]["extracted"], 1)
            self.assertEqual(result["extraction"]["skipped"], 0)
            self.assertNotIn("backup", result)
            rebuilt = Store.load(data / "diagnostics.json")
            identities.append(rebuilt.find("matches")["id"])
            self.assertEqual(rebuilt.count("reviews"), 1)
            self.assertEqual(validate_records(rebuilt), [])
        self.assertNotEqual(*identities)
        self.assertEqual(image.read_bytes(), image_bytes)
        self.assertEqual(outside.read_text(encoding="utf-8"), "not processing data")

    def test_launcher_process_runs_without_arguments_from_repository_root(self):
        repository = Path(__file__).resolve().parents[2]
        result = self.launcher("process")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                str(repository),
                "-m",
                "processing",
                "process",
            ],
        )

    def test_launcher_process_rejects_every_extra_argument(self):
        for arguments in (
            ("--limit", "2"),
            ("--screenshots", "73,74"),
            ("--clean",),
            ("--reextract",),
            ("--help",),
            ("anything",),
        ):
            with self.subTest(arguments=arguments):
                result = self.launcher("process", *arguments)
                self.assertEqual(result.returncode, 2)
                self.assertIn("accepts no arguments", result.stderr)
                self.assertEqual(result.stdout, "")

    def test_launcher_format_runs_both_formatters_from_repository_root(self):
        repository = Path(__file__).resolve().parents[2]

        result = self.launcher("format")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                str(repository),
                "--prefix",
                str(repository / "frontend"),
                "run",
                "format",
                str(repository),
                "-m",
                "ruff",
                "format",
                "--extend-exclude",
                "processing/data",
                "processing",
            ],
        )

    def test_launcher_format_rejects_extra_arguments(self):
        result = self.launcher("format", "--check")
        self.assertEqual(result.returncode, 2)
        self.assertIn("accepts no arguments", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_launcher_format_checks_ruff_before_running_prettier(self):
        result = self.launcher("format", python_exit=1)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Ruff is missing", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_launcher_only_exposes_start_process_and_format(self):
        for arguments in ((), ("-h",), ("--help",), ("help",)):
            with self.subTest(arguments=arguments):
                result = self.launcher(*arguments)
                self.assertEqual(result.returncode, 0, result.stderr)
                commands = [
                    line.split()[0]
                    for line in result.stdout.splitlines()
                    if line.startswith("  ")
                ]
                self.assertEqual(commands, ["start", "process", "format"])
        for command in (
            "dev",
            "build",
            "preview",
            "approve",
            "review",
            "status",
            "backup",
            "test",
            "e2e",
            "lint",
            "check",
            "inventory",
            "validate",
            "report",
            "reconcile",
            "export",
        ):
            with self.subTest(command=command):
                result = self.launcher(command)
                self.assertEqual(result.returncode, 2)
                self.assertIn(f"Unknown command: {command}", result.stderr)

    def test_process_exports_dashboard_json_without_approval(self):
        self.create_image()
        processed = self.command("process")
        self.assertEqual(processed["extraction"]["extracted"], 1)
        self.assertEqual(processed["import"]["imported_sources"], 1)
        self.assertIn("dashboard.json rebuilt directly", processed["message"])
        self.assertNotIn("next", processed)
        self.assertNotIn("review_file", processed)
        self.assertEqual(self.store.count("matches"), 1)
        self.assertEqual(len(self.command("data")["matches"]), 1)
        output = self.root / "frontend" / "public" / "data" / "dashboard.json"
        self.assertTrue(output.is_file())
        published = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(published["matches"], self.command("data")["matches"])
        self.assertEqual(
            published["processing"]["last_run"], processed["processing_run"]
        )
        self.assertNotIn("source_images", published)
        repeat = self.command("process")
        self.assertEqual(repeat["extraction"]["extracted"], 1)
        self.assertEqual(repeat["import"]["imported_sources"], 1)
        self.assertNotIn("review_file", repeat)
        self.assertEqual(self.extractor.extract.call_count, 2)
        self.assertNotIn("source_images", self.command("data"))
        self.assertNotEqual(json.loads(output.read_text(encoding="utf-8")), published)
        self.assertEqual(
            json.loads(output.read_text(encoding="utf-8"))["processing"]["last_run"],
            repeat["processing_run"],
        )

    def test_processing_timestamp_records_runs_not_dashboard_loads(self):
        self.create_image()
        first = self.command("process")["processing_run"]
        self.assertTrue(is_uuid(first["id"]))
        self.assertEqual(first["mode"], "clean")
        self.assertEqual(first["status"], "completed")
        self.assertEqual(first["extracted_images"], 1)
        self.assertTrue(first["completed_at"].endswith("+00:00"))
        self.assertEqual(self.command("data")["processing"]["last_run"], first)
        self.assertEqual(self.command("data")["processing"]["last_run"], first)
        self.assertEqual(
            self.store.count("processing_runs"),
            1,
        )

        repeated = self.command("process")["processing_run"]

        self.assertNotEqual(repeated["id"], first["id"])
        self.assertEqual(repeated["extracted_images"], 1)
        self.assertGreaterEqual(repeated["completed_at"], first["completed_at"])
        self.assertEqual(self.command("data")["processing"]["last_run"], repeated)
        self.assertEqual(
            self.store.count("processing_runs"),
            1,
        )

    def test_diagnostics_expose_last_ocr_without_inventing_a_run(self):
        self.command("export")
        self.assertEqual(
            self.command("data")["processing"],
            {"last_run": None, "last_extracted_at": None},
        )
        self.create_image()
        self.command("process")
        self.store.delete("processing_runs")
        self.update_records("extractions", {"extracted_at": "2026-09-13 06:27:18"})
        self.command("export")
        metadata = self.command("data")["processing"]

        self.assertIsNone(metadata["last_run"])
        self.assertEqual(metadata["last_extracted_at"], "2026-09-13T06:27:18+00:00")
        self.assertEqual(self.store.count("processing_runs"), 0)

    def test_processing_metadata_reports_skipped_imports(self):
        self.create_image()
        self.extractor.extract.return_value = {
            "screen_type": "squad",
            "records": [
                {"type": "player_snapshot", "player": "Test Player", "season": None}
            ],
            "evidence": {},
            "issues": [],
        }

        result = self.command("process", expected_exit=1)

        self.assertEqual(result["processing_run"]["status"], "partial")
        self.assertEqual(result["processing_run"]["skipped_sources"], 1)
        self.assertEqual(self.store.find("processing_runs"), result["processing_run"])

    def test_failed_rebuild_records_its_own_processing_metadata(self):
        self.create_image()
        first = self.command("process")["processing_run"]
        self.extractor.extract.side_effect = ValueError("OCR failed")

        failed = self.command("process", expected_exit=1)["processing_run"]

        self.assertNotEqual(failed["id"], first["id"])
        self.assertEqual(failed["status"], "partial")
        self.assertEqual(failed["extraction_errors"], 1)
        self.assertEqual(self.store.find("processing_runs"), failed)
        self.assertEqual(self.command("data")["processing"]["last_run"], first)
        self.extractor.extract.side_effect = None

        rebuilt = self.command("process")["processing_run"]

        self.assertEqual(rebuilt["mode"], "clean")
        self.assertNotEqual(rebuilt["id"], first["id"])
        self.assertEqual(self.command("data")["processing"]["last_run"], rebuilt)

    def test_process_discards_previously_extracted_candidates(self):
        self.create_image()
        inventory(self.store, self.root)
        extract_pending(self.store, self.root, extractor=self.extractor)

        result = self.command("process")

        self.assertEqual(result["extraction"]["extracted"], 1)
        self.assertEqual(result["import"]["imported_sources"], 1)
        self.assertEqual(len(self.command("data")["matches"]), 1)
        self.assertEqual(self.extractor.extract.call_count, 2)

    def test_process_automatically_links_player_screenshots(self):
        self.create_image()
        self.create_image("Screenshot (74).png", color="black")
        self.extractor.extract.side_effect = [
            self.extractor.extract.return_value,
            {
                "screen_type": "player_performance",
                "records": [
                    {
                        "type": "player_match",
                        "player": "Harry Kewell",
                        "club": "Notts County",
                        "match_id": None,
                        "rating": 7.5,
                        "goals": 1,
                    }
                ],
                "evidence": {},
                "issues": [],
            },
        ]

        result = self.command("process")

        self.assertEqual(result["import"]["imported_sources"], 2)
        self.assertEqual(result["import"]["skipped_sources"], [])
        data = self.command("data")
        self.assertEqual(
            data["player_matches"][0]["match_id"], data["matches"][0]["id"]
        )

    def test_process_rebuilds_team_counts_from_current_ocr(self):
        self.create_image()
        self.record["team_stats"] = {
            "home": {"corners": None},
            "away": {"corners": None},
        }
        self.extractor.extract.return_value["evidence"] = {
            "fields": {
                "home.corners": {"raw_text": "."},
                "away.corners": {"raw_text": "."},
            }
        }
        self.command("process")
        match_id = self.command("data")["matches"][0]["id"]
        self.update_records("extractions", {"extractor_version": "1.2.0"})
        self.record["team_stats"] = {"home": {"corners": 1}, "away": {"corners": 1}}

        result = self.command("process")

        self.assertEqual(result["extraction"]["extracted"], 1)
        self.assertEqual(result["import"]["imported_sources"], 1)
        data = self.command("data")
        self.assertNotEqual(data["matches"][0]["id"], match_id)
        self.assertEqual([team["corners"] for team in data["team_matches"]], [1, 1])
        self.assertEqual(self.command("process")["extraction"]["extracted"], 1)
        self.assertEqual(self.extractor.extract.call_count, 3)

    def test_process_rebuilds_known_images_without_backing_up_old_data(self):
        image = self.create_image()
        original_bytes = image.read_bytes()
        self.command("process")
        source_id = self.store.find("source_images")["id"]
        match_id = self.store.find("matches")["id"]
        cleaned = self.command("process")

        self.assertEqual(cleaned["inventory"]["new_images"], 1)
        self.assertEqual(cleaned["extraction"]["extracted"], 1)
        self.assertEqual(cleaned["extraction"]["skipped"], 0)
        self.assertEqual(cleaned["import"]["imported_sources"], 1)
        self.assertEqual(len(self.command("data")["matches"]), 1)
        self.assertNotEqual(self.command("data")["matches"][0]["id"], match_id)
        self.assertEqual(image.read_bytes(), original_bytes)
        self.assertNotIn("backup", cleaned)
        self.assertFalse((self.diagnostics_path.parent / "backups").exists())
        rebuilt = Store.load(cleaned["diagnostics"])
        self.assertNotEqual(rebuilt.find("source_images")["id"], source_id)
        self.assertEqual(rebuilt.count("reviews"), 1)
        self.assertEqual(validate_records(rebuilt), [])
        self.assertEqual(self.command("process")["extraction"]["extracted"], 1)
        self.assertEqual(self.extractor.extract.call_count, 3)

    def test_process_uses_new_ocr_not_saved_answers(self):
        self.create_image()
        self.command("process")
        document = make_review(self.store)
        document["sources"][0]["records"][0]["home_goals"] = 3
        approve_review(
            self.store, document, "Corrected visible score", replace_reviewed=True
        )
        self.command("export")
        old_match = self.command("data")["matches"][0]
        path = self.root / "processing" / "corrections.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(
            json.dumps({"schema_version": 99, "sources": {}}), encoding="utf-8"
        )

        result = self.command("process")

        self.assertEqual(result["import"]["skipped_sources"], [])
        rebuilt = self.command("data")["matches"][0]
        self.assertEqual(old_match["home_goals"], 3)
        self.assertEqual(rebuilt["home_goals"], 1)
        self.assertNotEqual(rebuilt["id"], old_match["id"])
        self.assertEqual(self.record["home_goals"], 1)
        self.assertEqual(self.command("process")["extraction"]["extracted"], 1)

    def test_process_ocr_failure_keeps_published_statistics(self):
        self.create_image()
        self.command("process")
        published = self.command("data")
        self.extractor.extract.side_effect = ValueError("OCR could not read the image")

        result = self.command("process", expected_exit=1)

        self.assertIn("previous dashboard.json was not replaced", result["message"])
        self.assertEqual(result["extraction"]["errors"], 1)
        self.assertEqual(self.command("data"), published)
        self.assertEqual(self.store.count("matches"), 0)

    def test_process_failed_import_retains_published_json_and_partial_diagnostics(self):
        self.create_image()
        self.command("process")
        published = self.command("data")
        self.record["played_on"] = None

        result = self.command("process", expected_exit=1)

        self.assertIn(
            "Extracted statistics could not be imported", result["validation_errors"][0]
        )
        self.assertEqual(self.command("data"), published)
        self.assertEqual(self.store.count("matches"), 0)
        self.assertEqual(self.store.count("extractions"), 1)

    def test_process_non_stat_screen_does_not_block_valid_stats(self):
        self.create_image()
        self.create_image("Screenshot (74).png", color="black")
        self.command("process")
        self.extractor.extract.side_effect = [
            self.extractor.extract.return_value,
            {
                "screen_type": "dashboard",
                "records": [],
                "evidence": {},
                "issues": [],
            },
        ]

        result = self.command("process")

        self.assertEqual(result["import"]["imported_sources"], 1)
        self.assertEqual(result["import"]["skipped_sources"], [])
        self.assertEqual(len(result["import"]["ignored_sources"]), 1)
        self.assertEqual(result["validation_errors"], [])
        self.assertEqual(result["processing_run"]["status"], "completed")
        self.assertEqual(result["processing_run"]["skipped_sources"], 0)
        self.assertEqual(len(self.command("data")["matches"]), 1)

    def test_process_recognized_stat_screen_without_records_is_not_ignored(self):
        self.create_image()
        self.extractor.extract.return_value = {
            "screen_type": "match_facts",
            "records": [],
            "evidence": {},
            "issues": ["Unsupported aspect ratio"],
        }

        result = self.command("process", expected_exit=1)

        self.assertEqual(result["import"]["ignored_sources"], [])
        self.assertEqual(len(result["import"]["skipped_sources"]), 1)
        self.assertEqual(result["processing_run"]["status"], "partial")
        self.assertTrue(result["validation_errors"])

    def test_process_rebuilds_default_diagnostics_without_touching_external_backup(
        self,
    ):
        match_id = self.create_match()
        other = self.root / "other.json"
        backup_records(self.store, other)
        self.create_image()

        result = self.command("process")

        self.assertEqual(
            result["diagnostics"],
            str(self.diagnostics_path.resolve()),
        )
        self.assertNotIn("backup", result)
        self.assertEqual(result["extraction"]["extracted"], 1)
        self.assertEqual(Store.load(result["diagnostics"]).count("matches"), 1)
        self.assertEqual(Store.load(other).find("matches")["id"], match_id)

    def test_process_with_empty_screenshot_folder_publishes_empty_json(self):
        self.create_match()

        result = self.command("process")

        self.assertEqual(result["inventory"]["files"], 0)
        self.assertEqual(result["extraction"]["extracted"], 0)
        self.assertNotIn("review_file", result)
        self.assertNotIn("backup", result)
        self.assertEqual(self.command("data")["matches"], [])
        self.assertFalse((self.diagnostics_path.parent / "backups").exists())
        self.extractor.extract.assert_not_called()

    def test_process_does_not_continue_when_folder_deletion_fails(self):
        match_id = self.create_match()

        with patch(
            "processing.__main__.shutil.rmtree",
            side_effect=OSError("Cannot remove data directory"),
        ):
            with self.assertRaisesRegex(OSError, "Cannot remove data directory"):
                self.command("process")

        self.assertEqual(self.store.find("matches")["id"], match_id)
        self.extractor.extract.assert_not_called()

    def test_process_rejects_removed_options_before_deleting_data(self):
        from processing.__main__ import main

        match_id = self.create_match()

        for arguments in (
            ("--limit", "1"),
            ("--screenshots", "73"),
            ("--clean",),
            ("--reextract",),
            ("anything",),
        ):
            with self.subTest(arguments=arguments):
                with (
                    redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit) as failure,
                ):
                    main(["--root", str(self.root), "process", *arguments])
                self.assertEqual(failure.exception.code, 2)
                self.assertEqual(
                    self.store.find("matches")["id"],
                    match_id,
                )
        self.extractor.extract.assert_not_called()

    def test_process_rejects_alternate_diagnostics_before_deleting_data(self):
        from processing.__main__ import main

        match_id = self.create_match()
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as failure:
            main(
                [
                    "--root",
                    str(self.root),
                    "--diagnostics",
                    str(self.root / "elsewhere.json"),
                    "process",
                ]
            )
        self.assertEqual(failure.exception.code, 2)
        self.assertEqual(self.store.find("matches")["id"], match_id)
        self.assertFalse((self.root / "elsewhere.json").exists())
        self.extractor.extract.assert_not_called()

    def test_process_rejects_symlinked_data_or_processing_directory(self):
        from processing.__main__ import main

        outside = self.root / "outside"
        outside.mkdir()
        sentinel = outside / "keep.txt"
        sentinel.write_text("preserve", encoding="utf-8")
        for part in ("processing", "data"):
            with self.subTest(part=part):
                root = self.root / f"test-{part}"
                root.mkdir()
                link = root / "processing"
                if part == "data":
                    link.mkdir()
                    link = link / "data"
                link.symlink_to(outside, target_is_directory=True)
                with self.assertRaisesRegex(
                    ValueError, "symlinked processing data directory"
                ):
                    main(["--root", str(root), "process"])
                self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")
        self.extractor.extract.assert_not_called()

    def test_process_discards_stale_diagnostics_and_writes_only_json(self):
        self.create_match()
        result = self.command("process")
        self.assertNotIn("backup", result)
        self.assertEqual(
            {path.name for path in self.diagnostics_path.parent.iterdir()},
            {"diagnostics.json", "processing-report.json"},
        )
        self.assertEqual(self.store.count("matches"), 0)
        self.assertEqual(self.command("data")["matches"], [])

    def test_process_rebuilds_only_present_unique_images(self):
        original = self.create_image()
        self.command("process")
        original.unlink()
        self.assertEqual(self.command("process")["extraction"]["extracted"], 0)
        self.assertEqual(self.command("data")["matches"], [])

        self.record["played_on"] = "2018-07-05"
        replacement = self.create_image(color="black")
        second = self.command("process")
        self.assertEqual(second["inventory"]["new_images"], 1)
        self.assertEqual(len(self.command("data")["matches"]), 1)
        (self.raw / "image-copy.png").write_bytes(replacement.read_bytes())
        duplicate = self.command("process")
        self.assertEqual(duplicate["inventory"]["files"], 2)
        self.assertEqual(duplicate["inventory"]["new_images"], 1)
        self.assertEqual(duplicate["extraction"]["extracted"], 1)
        self.assertEqual(len(self.command("data")["matches"]), 1)
        self.assertEqual(self.extractor.extract.call_count, 3)

    def test_process_has_no_silent_twenty_image_limit_or_image_copies(self):
        for sequence in range(21):
            self.create_image(
                f"Screenshot ({sequence}).png", color=(sequence * 10, 0, 0)
            )
        result = self.command("process")
        self.assertEqual(result["extraction"]["extracted"], 21)
        self.assertEqual(result["extraction"]["remaining"], 0)
        self.assertEqual(len(list(self.root.rglob("*.png"))), 21)

    def test_dashboard_read_does_not_create_missing_data(self):
        from processing.__main__ import main

        missing = self.root / "frontend" / "public" / "data" / "dashboard.json"
        with self.assertRaisesRegex(ValueError, "No dashboard.json"):
            main(["--root", str(self.root), "data"])
        self.assertFalse(missing.exists())


class ReconciliationTests(RecordTestCase):
    def prepare_stats(
        self, *, missing_goals=False, observed_on=None, snapshot_kind="season_end"
    ):
        self.create_image()
        inventory(self.store, self.root)
        self.create_match()
        self.player_id = self.create_player("Takefusa Kubo")
        source_id = self.store.find("source_images")["id"]
        insert_entity(
            self.store,
            "player_matches",
            {
                "match_id": self.match_id,
                "player_id": self.player_id,
                "club_id": self.home_club_id,
                "goals": None if missing_goals else 1,
                "assists": 1,
                "rating": 8.4,
                "displayed_position": "CAM",
            },
        )
        snapshot = {
            "player_id": self.player_id,
            "club_id": self.home_club_id,
            "season_id": self.season_id,
            "source_id": source_id,
            "scope": "all_competitions",
            "snapshot_kind": snapshot_kind,
            "observed_on": observed_on,
            "appearances": 1,
            "goals": 1,
            "assists": 1,
            "average_rating": 8.4,
        }
        self.snapshot_id = insert_entity(
            self.store, "player_competition_snapshots", snapshot
        )

    def test_reconciliation_counts_each_match_once_and_excludes_other_seasons(self):
        self.prepare_stats()
        next_edition = ensure_edition(
            self.store, {"competition": "Invitational Cup", "season": "2019/20"}
        )
        next_match = insert_entity(
            self.store,
            "matches",
            {
                "competition_season_id": next_edition,
                "played_on": "2019-07-07",
                "home_club_id": self.home_club_id,
                "away_club_id": self.away_club_id,
            },
        )
        insert_entity(
            self.store,
            "player_matches",
            {
                "match_id": next_match,
                "player_id": self.player_id,
                "club_id": self.home_club_id,
                "goals": 5,
                "assists": 5,
                "rating": 10,
            },
        )
        report = reconcile_totals(self.store, "2018/19")
        result = report["comparisons"][0]
        self.assertEqual(result["result"], "match")
        self.assertEqual(result["metrics"]["goals"]["derived"], 1)
        self.assertEqual(result["metrics"]["appearances"]["derived"], 1)
        self.assertEqual(
            self.store.count("player_matches"),
            2,
        )

    def test_unconfirmed_cutoff_is_not_compared(self):
        self.prepare_stats(snapshot_kind="in_season")
        report = reconcile_totals(self.store)
        self.assertEqual(report["summary"]["unconfirmed_cutoffs"], 1)
        self.assertEqual(report["comparisons"][0]["metrics"], {})

    def test_missing_match_goals_are_not_zero(self):
        self.prepare_stats(missing_goals=True)
        metric = reconcile_totals(self.store)["comparisons"][0]["metrics"]["goals"]
        self.assertEqual(metric["result"], "not_comparable")
        self.assertIsNone(metric["derived"])
        self.assertEqual(metric["missing_match_values"], 1)

    def test_missing_goalkeeper_goals_default_to_zero_without_changing_evidence(self):
        self.prepare_stats(missing_goals=True)
        self.update_records("player_matches", {"displayed_position": "GK"})
        self.update_records("player_competition_snapshots", {"goals": 0})

        report = reconcile_totals(self.store)
        comparison = report["comparisons"][0]
        goals = comparison["metrics"]["goals"]

        self.assertEqual(comparison["result"], "match")
        self.assertEqual(report["summary"]["partial_comparisons"], 0)
        self.assertEqual(goals["derived"], 0)
        self.assertEqual(goals["missing_match_values"], 0)
        self.assertEqual(goals["assumed_zero_match_values"], 1)
        self.assertIsNone(self.store.find("player_matches")["goals"])

    def test_dashboard_uses_the_same_goalkeeper_default_and_keeps_its_provenance(self):
        self.prepare_stats(missing_goals=True)
        self.update_records("player_competition_snapshots", {"goals": 0})
        for position, recorded, expected, assumed in (
            ("GK", None, 0, True),
            ("GK", 2, 2, False),
            ("CAM", None, None, False),
            (None, None, None, False),
        ):
            with self.subTest(position=position, recorded=recorded):
                self.update_records(
                    "player_matches",
                    {"displayed_position": position, "goals": recorded},
                )
                data = dashboard_data(self.store)
                performance = data["player_matches"][0]
                self.assertEqual(performance["goals"], expected)
                self.assertIs(performance["goals_assumed_zero"], assumed)
                self.assertEqual(
                    data["season_reconciliation"]["comparisons"][0]["metrics"]["goals"][
                        "derived"
                    ],
                    expected,
                )
                self.assertEqual(
                    self.store.find("player_matches")["goals"],
                    recorded,
                )

    def test_recorded_goalkeeper_goals_are_never_replaced(self):
        self.prepare_stats()
        self.update_records("player_matches", {"displayed_position": "GK"})
        goals = reconcile_totals(self.store)["comparisons"][0]["metrics"]["goals"]
        self.assertEqual(goals["result"], "match")
        self.assertEqual(goals["derived"], 1)
        self.assertEqual(goals["assumed_zero_match_values"], 0)

    def test_goalkeeper_rule_does_not_default_other_metrics_or_outfield_appearances(
        self,
    ):
        self.prepare_stats(missing_goals=True)
        self.update_records(
            "player_matches", {"displayed_position": "GK", "played_position": "ST"}
        )
        goals = reconcile_totals(self.store)["comparisons"][0]["metrics"]["goals"]
        self.assertIsNone(goals["derived"])
        self.assertEqual(goals["assumed_zero_match_values"], 0)

        self.update_records(
            "player_matches", {"played_position": "GK", "assists": None}
        )
        self.update_records("player_competition_snapshots", {"goals": 0})
        comparison = reconcile_totals(self.store)["comparisons"][0]
        self.assertEqual(comparison["result"], "partial_comparison")
        self.assertEqual(comparison["metrics"]["goals"]["derived"], 0)
        self.assertIsNone(comparison["metrics"]["assists"]["derived"])

    def test_goal_discrepancy_does_not_rewrite_either_source(self):
        self.prepare_stats()
        self.update_records("player_competition_snapshots", {"goals": 3})
        metric = reconcile_totals(self.store)["comparisons"][0]["metrics"]["goals"]
        self.assertEqual(metric["result"], "mismatch")
        self.assertEqual(metric["difference"], -2)
        self.assertEqual(self.store.find("player_matches")["goals"], 1)
        self.assertEqual(
            self.store.find("player_competition_snapshots")["goals"],
            3,
        )

    def test_display_average_is_truncated_without_losing_raw_mean(self):
        self.prepare_stats()
        self.update_records(
            "player_competition_snapshots",
            {"appearances": 2, "goals": 2, "assists": 2, "average_rating": 8.5},
        )
        second_match = insert_entity(
            self.store,
            "matches",
            {
                "competition_season_id": self.edition_id,
                "played_on": "2018-07-08",
                "home_club_id": self.home_club_id,
                "away_club_id": self.away_club_id,
            },
        )
        insert_entity(
            self.store,
            "player_matches",
            {
                "match_id": second_match,
                "player_id": self.player_id,
                "club_id": self.home_club_id,
                "goals": 1,
                "assists": 1,
                "rating": 8.7,
            },
        )
        metric = reconcile_totals(self.store)["comparisons"][0]["metrics"][
            "average_rating"
        ]
        self.assertEqual(metric["result"], "match")
        self.assertEqual(metric["raw_match_average"], 8.55)
        self.assertEqual(metric["derived"], 8.5)

    def test_dated_snapshot_excludes_later_matches(self):
        self.prepare_stats(observed_on="2018-07-04", snapshot_kind="in_season")
        later_match = insert_entity(
            self.store,
            "matches",
            {
                "competition_season_id": self.edition_id,
                "played_on": "2018-07-08",
                "home_club_id": self.home_club_id,
                "away_club_id": self.away_club_id,
            },
        )
        insert_entity(
            self.store,
            "player_matches",
            {
                "match_id": later_match,
                "player_id": self.player_id,
                "club_id": self.home_club_id,
                "goals": 5,
                "assists": 2,
                "rating": 10,
            },
        )
        comparison = reconcile_totals(self.store)["comparisons"][0]
        self.assertEqual(comparison["result"], "match")
        self.assertEqual(comparison["metrics"]["appearances"]["derived"], 1)

    def test_competition_scope_excludes_preseason_but_season_total_includes_it(self):
        self.prepare_stats()
        league_edition = ensure_edition(
            self.store, {"competition": "EFL League Two", "season": "2018/19"}
        )
        league_match = insert_entity(
            self.store,
            "matches",
            {
                "competition_season_id": league_edition,
                "played_on": "2018-08-04",
                "home_club_id": self.home_club_id,
                "away_club_id": self.away_club_id,
            },
        )
        insert_entity(
            self.store,
            "player_matches",
            {
                "match_id": league_match,
                "player_id": self.player_id,
                "club_id": self.home_club_id,
                "goals": 3,
                "assists": 0,
                "rating": 7.9,
            },
        )
        self.update_records(
            "player_competition_snapshots",
            {"appearances": 2, "goals": 4, "assists": 1, "average_rating": 8.1},
        )
        source_id = self.store.find("source_images")["id"]
        insert_entity(
            self.store,
            "player_competition_snapshots",
            {
                "player_id": self.player_id,
                "club_id": self.home_club_id,
                "season_id": self.season_id,
                "source_id": source_id,
                "scope": "competition",
                "competition_season_id": league_edition,
                "snapshot_kind": "season_end",
                "appearances": 1,
                "goals": 3,
                "assists": 0,
                "average_rating": 7.9,
            },
        )
        report = reconcile_totals(self.store)
        totals = {
            comparison["scope"]: comparison for comparison in report["comparisons"]
        }
        self.assertEqual(totals["competition"]["result"], "match")
        self.assertEqual(totals["all_competitions"]["result"], "match")
        self.assertEqual(totals["competition"]["metrics"]["goals"]["derived"], 3)
        self.assertEqual(totals["all_competitions"]["metrics"]["goals"]["derived"], 4)


if __name__ == "__main__":
    unittest.main()
