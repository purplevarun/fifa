import copy
import json
import unittest
from unittest.mock import Mock

from processing.confirmed_context import (
    apply_coverage_context,
    apply_record_context,
    load_context,
)
from processing.extraction import ScreenshotExtractor
from processing.pipeline import import_pending
from processing.store import Store, json_text


class ConfirmedContextTests(unittest.TestCase):
    def test_season_end_context_is_hash_bound_and_keeps_competition_scopes(self):
        policy = load_context()
        group = policy["season_ends"][1]
        records = [
            {
                "type": "player_competition_snapshot",
                "player": "Test Player",
                "season": None,
                "snapshot_kind": "in_season",
                "competition": "EFL League One Play-Offs",
                "goals": 2,
            }
        ]
        before = copy.deepcopy(records)
        updated = apply_record_context({"sha256": group["sources"][0][1]}, records)
        self.assertEqual(updated[0]["snapshot_kind"], "season_end")
        self.assertEqual(updated[0]["season"], "2019/20")
        self.assertEqual(updated[0]["competition"], "EFL League One Play-Offs")
        self.assertEqual(updated[0]["goals"], 2)
        self.assertNotIn("observed_on", updated[0])
        self.assertEqual(records, before)
        self.assertEqual(
            apply_record_context({"sha256": "0" * 64, "sequence": 1876}, records),
            records,
        )

    def test_new_import_applies_confirmations_without_saved_reviews(self):
        store = Store()
        group = load_context()["season_ends"][0]
        source = store.insert(
            "source_images",
            {
                "sha256": group["sources"][0][1],
                "byte_size": 1,
                "screen_type": "squad",
                "status": "needs_review",
            },
        )
        store.insert(
            "source_paths",
            {
                "path": "raw_screenshots/908.png",
                "sequence": 908,
                "source_id": source["id"],
            },
        )
        candidate = {
            "type": "player_competition_snapshot",
            "player": "Test Player",
            "club": "Notts County",
            "competition": "EFL League Two",
            "season": None,
            "scope": "competition",
            "snapshot_kind": "in_season",
            "goals": 2,
        }
        store.insert(
            "extractions",
            {
                "source_id": source["id"],
                "extractor_version": "test",
                "candidate_json": json_text([candidate]),
                "evidence_json": "{}",
                "issues_json": "[]",
            },
        )
        result = import_pending(store)
        self.assertEqual(result["skipped_sources"], [])
        self.assertEqual(result["imported_sources"], 1)
        self.assertEqual(
            store.rows("player_competition_snapshots")[0]["snapshot_kind"], "season_end"
        )
        self.assertEqual(
            json.loads(store.get("extractions", source["id"])["candidate_json"])[0],
            candidate,
        )

    def test_kubo_interest_keeps_assumed_date_but_removes_stat_snapshot(self):
        policy = load_context()
        original = [
            {
                "type": "player_competition_snapshot",
                "player": "Takefusa Kubo",
                "club": "Notts County",
                "assists": 12,
            }
        ]
        record = apply_record_context(
            {"sha256": policy["transfer_interest"]["source"][1]}, original
        )[0]
        self.assertEqual(record["type"], "competition_event")
        self.assertEqual(record["event_type"], "transfer_interest")
        self.assertEqual(record["period"], "2021-02-03")
        self.assertIsNone(record["announced_on"])
        self.assertIn("Assumed observation date", record["description"])
        self.assertNotIn("assists", record)
        self.assertNotIn("transfer_type", record)
        self.assertEqual(original[0]["assists"], 12)

    def test_confirmed_459_is_an_extra_time_win_without_a_review_warning(self):
        policy = load_context()
        source = next(
            check["source"]
            for check in policy["match_checks"]
            if check["source"][0] == 459
        )
        record = apply_record_context(
            {"sha256": source[1]}, [{"type": "match", "home_goals": 1, "away_goals": 1}]
        )[0]
        self.assertEqual((record["home_goals"], record["away_goals"]), (1, 2))
        self.assertEqual(record["duration_minutes"], 120)
        self.assertTrue(record["extra_time"])
        self.assertEqual(policy["pending_conflicts"], [])

        store = Mock()
        store.rows.return_value = [{"source_id": "source", "match_id": "match"}]
        store.get.return_value = {"sha256": source[1]}
        report = {
            "matches": [
                {"match_id": "match", "goal_difference": 0, "assumed_own_goals": 0}
            ],
            "warnings": [],
            "summary": {},
        }
        previous = copy.deepcopy(policy)
        previous["pending_conflicts"] = [
            {
                "source": source,
                "owner_reported": "1–1 after extra time",
                "fresh_ocr": "1–2 after extra time",
            }
        ]
        self.assertEqual(
            apply_coverage_context(
                store, copy.deepcopy(report), "Notts County", previous
            )["warnings"][0]["code"],
            "manual_score_conflict",
        )
        resolved = apply_coverage_context(
            store, copy.deepcopy(report), "Notts County", policy
        )
        self.assertEqual(resolved["warnings"], [])
        self.assertEqual(resolved["summary"]["warning_count"], 0)

    def test_confirmed_own_goals_do_not_change_scores_and_conflicts_are_reported(self):
        store = Mock()
        store.rows.return_value = [{"source_id": "source", "match_id": "match"}]
        store.get.return_value = {
            "sha256": load_context()["opponent_own_goals"][0]["source"][1]
        }
        for difference in (1, 2):
            report = {
                "matches": [
                    {
                        "match_id": "match",
                        "goal_difference": difference,
                        "assumed_own_goals": difference,
                    }
                ],
                "warnings": [],
                "summary": {},
            }
            result = apply_coverage_context(store, report, "Notts County")
            self.assertEqual(result["matches"][0]["goal_difference"], difference)
            self.assertEqual(
                result["summary"]["confirmed_own_goals"], 1 if difference == 1 else 0
            )
            self.assertEqual(
                result["summary"]["assumed_own_goals"], 0 if difference == 1 else 2
            )
            self.assertEqual(len(result["warnings"]), 0 if difference == 1 else 1)

    def test_clock_spacing_and_penalty_scores_remain_separate(self):
        for clock, duration, extra_time, penalties in (
            ("1 20:00 ET ,", 120, True, (None, None)),
            ("120:00 et", 120, True, (None, None)),
            ("90:00", 90, False, (None, None)),
            ("(4-2) PEN", None, None, (4, 2)),
            ("(1-2) PEN ,", None, None, (1, 2)),
        ):
            with self.subTest(clock=clock):
                extractor = ScreenshotExtractor(engine=Mock())
                extractor.recognize = lambda image, regions, integer_fields: {
                    key: {"raw_text": clock if key == "clock" else "1"}
                    for key in regions
                }
                record, _ = extractor.extract_match(Mock())
                self.assertEqual((record["home_goals"], record["away_goals"]), (1, 1))
                self.assertEqual(record["duration_minutes"], duration)
                self.assertEqual(record["extra_time"], extra_time)
                self.assertEqual(
                    (record["home_penalties"], record["away_penalties"]), penalties
                )
