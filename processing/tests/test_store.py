import copy
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

from processing.catalog import inventory, validate_records
from processing.identifiers import is_uuid, new_id, normalize_references, resolve_id
from processing.pipeline import approve_review, ensure_club, ensure_edition
from processing.store import Store, insert_entity, write_json


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.store = Store()

    def fixture(self):
        edition = ensure_edition(
            self.store, {"competition": "EFL League Two", "season": "2018/19"}
        )
        home = ensure_club(self.store, "Notts County")
        away = ensure_club(self.store, "Dundee FC")
        return self.store.insert(
            "matches",
            {
                "competition_season_id": edition,
                "played_on": "2018-07-04",
                "home_club_id": home,
                "away_club_id": away,
            },
        )

    def test_ids_are_distinct_canonical_uuids(self):
        identifiers = {new_id() for _ in range(100)}
        self.assertEqual(len(identifiers), 100)
        self.assertTrue(all(is_uuid(value) for value in identifiers))
        for invalid in (
            1,
            "1",
            True,
            None,
            "",
            "a" * 64,
            "00000000-0000-0000-0000-000000000000",
        ):
            self.assertFalse(is_uuid(invalid))

    def test_reference_validation_needs_no_legacy_mapping(self):
        identifier = new_id()
        self.assertEqual(resolve_id("matches", identifier), identifier)
        self.assertIsNone(resolve_id("matches", None))
        for value in (1, "1", True, "not-a-uuid"):
            with self.assertRaises(ValueError):
                resolve_id("matches", value)
        document = {
            "sources": [{"source_id": identifier}],
            "nationality_basis": {"fifa19_id": 158023},
        }
        self.assertEqual(normalize_references(document), document)

    def test_image_identity_and_review_history_survive_json_round_trip(self):
        raw = self.root / "raw_screenshots"
        raw.mkdir()
        Image.new("RGB", (40, 20), "white").save(raw / "1.png")
        self.assertEqual(inventory(self.store, self.root)["new_images"], 1)
        source = self.store.find("source_images")
        self.assertTrue(is_uuid(source["id"]))
        self.assertEqual(len(source["sha256"]), 64)
        self.assertEqual(inventory(self.store, self.root)["new_images"], 0)
        self.assertEqual(self.store.find("source_images")["id"], source["id"])
        record = {
            "type": "match",
            "season": "2018/19",
            "competition": "EFL League Two",
            "played_on": "2018-07-04",
            "home_club": "Notts County",
            "away_club": "Dundee FC",
            "home_goals": 1,
            "away_goals": 1,
        }
        document = {
            "schema_version": 4,
            "sources": [
                {"source_id": source["id"], "complete": True, "records": [record]}
            ],
        }
        approve_review(self.store, document, "Synthetic review")
        self.assertEqual(
            approve_review(self.store, document, "Repeat")["skipped_reviews"], 1
        )
        corrected = copy.deepcopy(document)
        corrected["sources"][0]["records"][0]["home_goals"] = 2
        approve_review(
            self.store, corrected, "Synthetic correction", replace_reviewed=True
        )
        path = self.root / "diagnostics.json"
        self.store.save(path)
        loaded = Store.load(path)
        self.assertEqual(loaded.rows("reviews"), self.store.rows("reviews"))
        self.assertEqual(loaded.latest_review(source["id"])["revision"], 2)
        self.assertEqual(loaded.find("matches")["home_goals"], 2)
        self.assertEqual(validate_records(loaded), [])

    def test_nested_rollback_restores_records_and_unique_indexes(self):
        original = self.store.insert("clubs", {"name": "Original"})
        with self.assertRaisesRegex(ValueError, "abort"):
            with self.store.transaction():
                self.store.update("clubs", original["id"], {"name": "Renamed"})
                with self.store.transaction():
                    self.store.insert("clubs", {"name": "Temporary"})
                raise ValueError("abort")
        self.assertEqual(self.store.find("clubs", name="Original"), original)
        self.assertIsNone(self.store.find("clubs", name="Renamed"))
        self.assertIsNone(self.store.find("clubs", name="Temporary"))
        self.store.insert("clubs", {"name": "Renamed"})
        self.assertEqual(self.store.validate(), [])

    def test_failed_nested_transaction_does_not_discard_outer_work(self):
        with self.store.transaction():
            self.store.insert("clubs", {"name": "Keep"})
            with self.assertRaises(ValueError):
                with self.store.transaction():
                    self.store.insert("clubs", {"name": "Discard"})
                    raise ValueError("abort nested")
        self.assertEqual([row["name"] for row in self.store.rows("clubs")], ["Keep"])

    def test_parent_update_cannot_invalidate_match_participants(self):
        fixture = self.fixture()
        player = insert_entity(self.store, "players", {"name": "Test Player"})
        self.store.insert(
            "player_matches",
            {
                "match_id": fixture["id"],
                "player_id": player,
                "club_id": fixture["home_club_id"],
            },
        )
        other = ensure_club(self.store, "Other Club")
        with self.assertRaisesRegex(ValueError, "related records"):
            self.store.update("matches", fixture["id"], {"home_club_id": other})
        self.assertEqual(self.store.get("matches", fixture["id"]), fixture)
        self.assertEqual(self.store.validate(), [])

    def test_deleting_a_referenced_entity_is_rolled_back(self):
        fixture = self.fixture()
        with self.assertRaisesRegex(ValueError, "referenced"):
            self.store.delete("clubs", id=fixture["home_club_id"])
        self.assertIsNotNone(self.store.get("clubs", fixture["home_club_id"]))
        self.assertEqual(self.store.validate(), [])

    def test_reads_cannot_mutate_working_records(self):
        club = self.store.insert("clubs", {"name": "Original"})
        self.store.get("clubs", club["id"])["name"] = "Changed"
        self.store.rows("clubs")[0]["name"] = "Changed"
        self.assertEqual(self.store.get("clubs", club["id"])["name"], "Original")

    def test_primary_keys_and_unique_identities_are_enforced(self):
        club = self.store.insert("clubs", {"name": "Original"})
        with self.assertRaises(ValueError):
            self.store.update("clubs", club["id"], {"id": new_id()})
        with self.assertRaises(ValueError):
            self.store.insert("clubs", {"name": "Original"})
        self.assertEqual(self.store.count("clubs"), 1)

    def test_json_load_is_independent_of_collection_order(self):
        self.fixture()
        path = self.root / "diagnostics.json"
        self.store.save(path)
        document = json.loads(path.read_text())
        document["tables"] = dict(reversed(list(document["tables"].items())))
        write_json(path, document)
        loaded = Store.load(path)
        self.assertEqual(loaded.rows("matches"), self.store.rows("matches"))

    def test_invalid_json_records_are_rejected_without_mutating_existing_store(self):
        fixture = self.fixture()
        path = self.root / "diagnostics.json"
        self.store.save(path)
        baseline = json.loads(path.read_text())
        for change in (
            {"home_club_id": new_id()},
            {"id": []},
            {"home_goals": float("nan")},
            {"home_goals": True},
            {"home_goals": -1},
        ):
            document = copy.deepcopy(baseline)
            document["tables"]["matches"][0].update(change)
            path.write_text(json.dumps(document))
            with self.assertRaises(ValueError):
                Store.load(path)
            self.assertEqual(self.store.find("matches"), fixture)
        document = copy.deepcopy(baseline)
        document["tables"]["matches"].append(document["tables"]["matches"][0])
        write_json(path, document)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            Store.load(path)

    def test_atomic_json_failure_keeps_the_previous_export(self):
        path = self.root / "dashboard.json"
        write_json(path, {"previous": True})
        before = path.read_bytes()
        with patch(
            "processing.store.os.replace", side_effect=OSError("disk unavailable")
        ):
            with self.assertRaises(OSError):
                write_json(path, {"new": True})
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.root.iterdir()), [path])
        with self.assertRaises(ValueError):
            write_json(path, {"invalid": float("nan")})
        self.assertEqual(path.read_bytes(), before)

    def test_processing_runs_when_database_modules_are_unavailable(self):
        from processing.__main__ import main

        raw = self.root / "raw_screenshots"
        raw.mkdir()
        Image.new("RGB", (40, 20), "white").save(raw / "1.png")
        extractor = Mock()
        extractor.extract.return_value = {
            "screen_type": "dashboard",
            "records": [],
            "evidence": {},
            "issues": [],
        }
        with (
            patch.dict(sys.modules, {"sqlite3": None, "_sqlite3": None}),
            patch("processing.extraction.ScreenshotExtractor", return_value=extractor),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(main(["--root", str(self.root), "process"]), 0)
        self.assertTrue((self.root / "frontend/public/data/dashboard.json").is_file())
        self.assertEqual(
            {path.suffix for path in (self.root / "processing/data").iterdir()},
            {".json"},
        )


if __name__ == "__main__":
    unittest.main()
