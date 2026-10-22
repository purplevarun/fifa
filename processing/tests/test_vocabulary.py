import json
import unittest
from pathlib import Path
from unittest.mock import Mock

from processing.extraction import ScreenshotExtractor, parse_news_event
from processing.tests.test_extraction import ocr_tokens
from processing.vocabulary import Vocabulary, split_joined_words


class VocabularyTests(unittest.TestCase):
    def test_shared_cases_match_frontend_spacing_and_preserve_characters(self):
        path = Path(__file__).with_name("fixtures") / "vocab_cases.json"
        for case in json.loads(path.read_text(encoding="utf-8")):
            with self.subTest(text=case["input"]):
                split = (
                    Vocabulary(case["words"]).split_text
                    if "words" in case
                    else split_joined_words
                )
                result = split(case["input"])
                self.assertEqual(result, case["expected"])
                self.assertEqual(split(result), result)
                self.assertEqual(
                    "".join(result.split()), "".join(case["input"].split())
                )

    def test_long_and_non_english_tokens_are_untouched(self):
        for value in (
            "goals" * 1000,
            "球Countyearned",
            "e\u0301Countyearned",
            "forNotts_unknown",
        ):
            self.assertEqual(split_joined_words(value), value)

    def test_invalid_word_entries_fail_explicitly(self):
        for words in ([""], ["two words"], ["FIFA19"], ["typo!"], [1], None):
            with self.subTest(words=words), self.assertRaises(ValueError):
                Vocabulary(words)

    def test_joined_titles_and_bodies_parse_without_rewriting_ocr_evidence(self):
        title = "KubograbsAugustPlayeroftheMonthAward"
        body = (
            "Kubo'simpressiveperformanceforNotts Countyearned himthe "
            "EFLChampionship PlayeroftheMonth award for August."
        )
        tokens = ocr_tokens(
            [
                (title, 960, 230, 1250, 245),
                (body, 960, 280, 1250, 310),
                ("PA FIFA19 AFIFA19 EAFIFA19", 960, 580, 1250, 600),
                (title, 100, 210, 360, 240),
                ("01/09/2020", 100, 250, 225, 265),
            ]
        )
        records, fields, _ = ScreenshotExtractor(engine=Mock()).extract_news(tokens)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["player"], "Kubo")
        self.assertEqual(record["club"], "Notts County")
        self.assertEqual(record["competition"], "EFL Championship")
        self.assertEqual(record["period"], "2020-08")
        self.assertIn(
            "Kubo's impressive performance for Notts County earned him the",
            record["description"],
        )
        self.assertNotIn("FIFA19", record["description"])
        self.assertEqual(fields["article.title"]["raw_text"], title)
        self.assertIn(body, fields["article.body"]["raw_text"])
        self.assertIn("AFIFA19", fields["article.body"]["raw_text"])

    def test_vocabulary_repair_does_not_turn_predictions_into_awards(self):
        self.assertIsNone(parse_news_event("Haaland likely PlayeroftheMonth"))
