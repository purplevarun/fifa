import os
import unittest
from pathlib import Path
from unittest.mock import Mock

from PIL import Image

from processing.extraction import (
    ScreenshotExtractor,
    classify,
    clean_news_text,
    parse_calendar_month,
    parse_counts,
    parse_header,
    parse_integer,
    parse_money,
    parse_months,
    parse_news_date,
    parse_news_event,
)


def ocr_tokens(lines):
    return [
        {
            "text": text,
            "confidence": 0.99,
            "box": [
                [left / 1366, top / 768],
                [right / 1366, top / 768],
                [right / 1366, bottom / 768],
                [left / 1366, bottom / 768],
            ],
        }
        for text, left, top, right, bottom in lines
    ]


class ParsingTests(unittest.TestCase):
    def test_missing_values_are_not_zero(self):
        self.assertEqual(parse_integer("0"), 0)
        for text in ("", "O", "-", "1 0", "unknown"):
            self.assertIsNone(parse_integer(text))
        self.assertEqual(parse_counts("0/1/0", 3), [0, 1, 0])
        self.assertEqual(parse_counts("0/1", 3), [None, None, None])

    def test_preseason_header_and_season(self):
        header = parse_header("04 July 2018 | San Siro | European Int'l Cup")
        self.assertEqual(header["competition"], "European International Cup")
        self.assertEqual(header["played_on"], "2018-07-04")
        self.assertEqual(header["season"], "2018/19")
        self.assertEqual(header["venue"], "San Siro")
        self.assertEqual(
            parse_header("14 February 2019 | Ivy Lane | Checkatrade Trophy")["season"],
            "2018/19",
        )

    def test_bad_dates_are_not_invented(self):
        self.assertIsNone(
            parse_header("31 February 2019 | Town Park | EFL League Two")["played_on"]
        )
        self.assertEqual(
            parse_header("260ctober2019/Ivy Lane/EFLLeague One")["played_on"],
            "2019-10-26",
        )

    def test_dashboard_tile_is_not_transfer_screen(self):
        self.assertEqual(classify("Mr. Kedia TRANSFER HUB STANDINGS"), "dashboard")
        self.assertEqual(classify("CAREER > TRANSFER HUB SENT OFFERS"), "transfer")
        self.assertEqual(
            classify("PLAYER PERFORMANCE GOALKEEPING"), "goalkeeper_performance"
        )
        self.assertEqual(
            classify("STANDINGS Kubo grabs August Player of the Month Award"),
            "dashboard_award",
        )
        self.assertEqual(
            classify("STANDINGS Player of the Month August shortlist"), "dashboard"
        )
        self.assertEqual(
            classify(
                "ROUND 1 ROUND 2 ROUND 3 ROUND 4 QUARTER-FINALS SEMI FINALS "
                "FINAL WINNER LIVERPOOL LIVERPOOL 2 - 1 NOTTS COUNTY"
            ),
            "knockout_bracket",
        )
        self.assertEqual(
            classify("Central News Liverpool wins the fourth round 1-0"), "news"
        )

    def test_money_uses_minor_units_without_guessing_dollar_currency(self):
        self.assertEqual(parse_money("$33,601"), (3360100, None, "$"))
        self.assertEqual(parse_money("GBP 1.25M"), (125000000, "GBP", "GBP"))
        self.assertEqual(parse_money("\u20ac750K"), (75000000, "EUR", "\u20ac"))
        self.assertEqual(parse_money("USD 0"), (0, "USD", "USD"))
        for text in ("", "$5,9OO", "35,99", "2-Year", "unknown"):
            self.assertIsNone(parse_money(text)[0])

    def test_contract_and_loan_durations(self):
        for text, expected in (
            ("2-Year", 24),
            ("1 Year(s]", 12),
            ("3 Year(s)", 36),
            ("6 Months", 6),
        ):
            self.assertEqual(parse_months(text), expected)
        for text in ("", "0 Years", "Unknown", "$12"):
            self.assertIsNone(parse_months(text))

    def test_monthly_award_uses_award_month_for_year_and_season(self):
        december = parse_news_event(
            "King grabs December Player of the Month Award", announced_on="2019-01-05"
        )
        self.assertEqual(
            (december["period"], december["season"]), ("2018-12", "2018/19")
        )
        june = parse_news_event(
            "King wins June Player of the Month", announced_on="2019-07-05"
        )
        self.assertEqual((june["period"], june["season"]), ("2019-06", "2018/19"))
        unknown_date = parse_news_event("King grabs August Player of the Month Award")
        self.assertEqual(unknown_date["period"], "August")
        self.assertIsNone(unknown_date["season"])
        self.assertIsNone(unknown_date["competition"])
        self.assertEqual(parse_news_date("05/09/2018"), "2018-09-05")
        self.assertIsNone(parse_news_date("31/02/2019"))
        self.assertIsNone(parse_news_date("NEW!"))

    def test_news_text_drops_only_repeated_sponsor_logo_footers(self):
        body = "Kubo earned the EFL Championship Player of the Month award for August."
        footers = (
            "PA FIFA19 AFIFA19 EAFIFA19 EFL AFIFA19 AFIFA19",
            "PA FIFA19 AFIFA19 EAFIFR19 AFIFA19 FAFIFA19",
            "LEASUETW RA FIFA19 AFIFA19 EA FIFR19 EFL GA FIFA19 AFIFA19",
            "LEASUETW PA FIFR19 EFL AFIFA19 EAFIFA19 EFL AFIFA19 AFIFA19",
            "PA FIFA19 AFIFA19 EAFIFA19 EFL A FIFA19 AFIFA19",
        )
        for footer in footers:
            with self.subTest(footer=footer):
                self.assertEqual(clean_news_text(f"{body} {footer}"), body)
                event = parse_news_event(
                    "Kubo grabs August Player of the Month Award",
                    f"{body} {footer}",
                    announced_on="2020-09-01",
                )
                self.assertTrue(event["description"].endswith(body))
                self.assertEqual(event["competition"], "EFL Championship")
                self.assertEqual(event["period"], "2020-08")
        for text in (
            "An award in FIFA 19.",
            "An award in FIFA19",
            "FIFA19 and FIFA19 players celebrate.",
            "Award confirmed. PA",
            "EFL League One champions",
            "",
        ):
            with self.subTest(text=text):
                self.assertEqual(clean_news_text(text), text)

    def test_sponsor_cleanup_preserves_raw_news_evidence(self):
        title = "Kubo grabs August Player of the Month Award"
        body = "Kubo earned the EFL Championship Player of the Month award for August."
        footer = "PA FIFA19 AFIFA19 EAFIFA19"
        records, fields, _ = ScreenshotExtractor(engine=Mock()).extract_news(
            ocr_tokens(
                [
                    (title, 960, 230, 1250, 245),
                    (body, 960, 280, 1250, 310),
                    (footer, 960, 580, 1250, 600),
                    (title, 100, 210, 360, 240),
                    ("01/09/2020", 100, 250, 225, 265),
                ]
            )
        )
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0]["description"].endswith(body))
        self.assertNotIn("AFIFA19", records[0]["description"])
        self.assertIn(footer, fields["article.body"]["raw_text"])

    def test_dashboard_calendar_is_not_an_award_announcement_date(self):
        self.assertEqual(parse_calendar_month("Monday,Feb18,2019"), "2019-02")
        self.assertEqual(parse_calendar_month("APR2019"), "2019-04")
        self.assertIsNone(parse_calendar_month("Feb31,2019"))
        self.assertIsNone(parse_calendar_month("March"))
        award = parse_news_event(
            "Haaland grabs March Player of the Month Award", observed_on="2019-04-01"
        )
        self.assertEqual(award["period"], "2019-03")
        self.assertIsNone(award["announced_on"])

    def test_award_shortlists_predictions_and_unnamed_winners_are_not_records(self):
        for title in (
            "EFL League Two Player of the Month September shortlist",
            "King nominated for Player of the Month",
            "Exeter City Fans Expect Promotion",
            "Player of the Competition Announced",
            "Player of the Year Announced",
            "Lionel Messi nominated for Player of the Year",
            "Lionel Messi likely Player of the Year",
            "Team of the Competition Announced",
        ):
            self.assertIsNone(parse_news_event(title))

    def test_dashboard_champions_and_annual_awards_are_supported(self):
        for headline in (
            "Notts County Crowned EFL League Two Champions",
            "Player of the Year Announced Lionel Messi",
            "Erling Haaland wins Player of the Year Award",
        ):
            with self.subTest(headline=headline):
                self.assertEqual(classify(f"STANDINGS {headline}"), "dashboard_award")
        champion = parse_news_event(
            "Notts County Crowned EFL League Two Champions", observed_on="2019-05-01"
        )
        self.assertEqual(champion["event_type"], "champion")
        self.assertEqual(champion["club"], "Notts County")
        self.assertEqual(champion["competition"], "EFL League Two")
        self.assertEqual(champion["season"], "2018/19")
        self.assertIsNone(champion["announced_on"])

    def test_annual_awards_use_named_winners_and_calendar_years(self):
        for title, body, expected_player, expected_year in (
            ("Player of the Year Announced Lionel Messi", "", "Lionel Messi", "2019"),
            (
                "Erling Haaland wins Player of the Year Award",
                "",
                "Erling Haaland",
                "2019",
            ),
            ("Lionel Messi wins 2018 Player of the Year", "", "Lionel Messi", "2018"),
            (
                "Player of the Year Announced",
                "Lionel Messi has been named Player of the Year.",
                "Lionel Messi",
                "2019",
            ),
        ):
            with self.subTest(title=title, body=body):
                record = parse_news_event(title, body, observed_on="2019-12-01")
                self.assertEqual(record["event_type"], "player_of_the_year")
                self.assertEqual(record["player"], expected_player)
                self.assertEqual(record["period"], expected_year)
                for field in ("competition", "club", "season", "announced_on"):
                    self.assertIsNone(record[field])

    def test_annual_award_without_a_year_keeps_it_unknown(self):
        record = parse_news_event("Player of the Year Announced Lionel Messi")
        self.assertIsNone(record["period"])
        self.assertIsNone(record["season"])

    def test_sidebar_awards_ignore_incidental_golden_boot_but_keep_global_poty(self):
        self.assertIsNone(
            parse_news_event(
                "Zoko Wins Golden Boot", announced_on="2019-05-04", sidebar=True
            )
        )
        record = parse_news_event(
            "Player of the Year Announced Lionel Messi",
            announced_on="2019-12-12",
            sidebar=True,
        )
        self.assertEqual(record["event_type"], "player_of_the_year")
        self.assertEqual(record["player"], "Lionel Messi")
        self.assertEqual(record["period"], "2019")
        foreign = parse_news_event(
            "Player of the Year Announced",
            "Other FC's Visiting Player has been named the Player of the Year.",
            announced_on="2020-12-12",
        )
        self.assertEqual(foreign["player"], "Visiting Player")
        self.assertEqual(foreign["club"], "Other FC")
        self.assertEqual(foreign["event_type"], "player_of_the_year")

    def test_annual_award_article_uses_an_explicit_club_without_merging_it_into_the_name(
        self,
    ):
        record = parse_news_event(
            "Player of the Year Announced",
            "FC Barcelona's Lionel Messi has been named the Player of the Year.",
            announced_on="2019-12-12",
        )
        self.assertEqual(record["player"], "Lionel Messi")
        self.assertEqual(record["club"], "FC Barcelona")
        self.assertEqual(record["period"], "2019")
        self.assertIsNone(record["competition"])


class NumericRecognitionTests(unittest.TestCase):
    def setUp(self):
        self.image = Image.new("RGB", (1366, 768), "white")
        self.image.paste((70, 70, 70), (8, 3, 13, 17))
        self.regions = {"assists": (0, 0, 30, 20)}

    def test_agreeing_repeated_digits_preserve_initial_evidence(self):
        for digit in ("0", "1"):
            with self.subTest(digit=digit):
                engine = Mock()
                engine.text_recognizer.side_effect = [
                    ([(".", 0.2)], 0),
                    ([(digit * 3, 0.7), (digit * 5, 0.8)], 0),
                ]
                fields = ScreenshotExtractor(engine).recognize(
                    self.image, self.regions, {"assists"}
                )
                self.assertEqual(fields["assists"]["raw_text"], digit)
                self.assertEqual(
                    fields["assists"]["initial_reading"],
                    {"raw_text": ".", "confidence": 0.2},
                )
                self.assertEqual(
                    fields["assists"]["method"], "rapidocr_repeated_digit_crop"
                )
                self.assertEqual(len(fields["assists"]["numeric_retry"]), 2)

    def test_ambiguous_or_low_confidence_readings_are_not_numbers(self):
        for readings in (
            [("111", 0.9), ("77777", 0.9)],
            [("000", 0.59), ("00000", 0.9)],
            [("OOO", 0.9), ("OOOOO", 0.9)],
            [("121212", 0.9), ("1212121212", 0.9)],
            [("11", 0.9), ("11111", 0.9)],
            [("", 0), ("11111", 0.9)],
        ):
            with self.subTest(readings=readings):
                engine = Mock()
                engine.text_recognizer.side_effect = [([(".", 0.2)], 0), (readings, 0)]
                fields = ScreenshotExtractor(engine).recognize(
                    self.image, self.regions, {"assists"}
                )
                self.assertIsNone(parse_integer(fields["assists"]["raw_text"]))
                self.assertNotIn("initial_reading", fields["assists"])

    def test_known_values_and_text_fields_are_not_retried(self):
        for text, selected in (("7", {"assists"}), ("name", set())):
            with self.subTest(text=text):
                engine = Mock()
                engine.text_recognizer.return_value = ([(text, 0.5)], 0)
                fields = ScreenshotExtractor(engine).recognize(
                    self.image, self.regions, selected
                )
                self.assertEqual(fields["assists"]["raw_text"], text)
                engine.text_recognizer.assert_called_once()

    def test_blank_and_dash_cells_remain_unknown(self):
        for mark in (False, True):
            with self.subTest(mark=mark):
                image = Image.new("RGB", (1366, 768), "white")
                if mark:
                    image.paste((70, 70, 70), (8, 9, 20, 11))
                engine = Mock()
                engine.text_recognizer.return_value = ([("-", 0.5)], 0)
                fields = ScreenshotExtractor(engine).recognize(
                    image, self.regions, {"assists"}
                )
                self.assertIsNone(parse_integer(fields["assists"]["raw_text"]))
                engine.text_recognizer.assert_called_once()


class NameRecognitionTests(unittest.TestCase):
    def setUp(self):
        self.extractor = ScreenshotExtractor(engine=Mock())
        self.image = Image.new("RGB", (1366, 768), "white")
        self.fields = {
            "first_name": {
                "raw_text": "Elliott",
                "confidence": 0.8,
                "box": [175 / 1366, 139 / 768, 404 / 1366, 163 / 768],
            },
            "last_name": {
                "raw_text": "HewittO",
                "confidence": 0.8,
                "box": [175 / 1366, 163 / 768, 404 / 1366, 190 / 768],
            },
        }
        self.tokens = ocr_tokens(
            [("Elliott", 177, 140, 240, 160), ("Hewitt", 177, 164, 251, 187)]
        )

    def test_agreeing_name_readings_preserve_original_evidence(self):
        self.extractor.recognize = Mock(
            return_value={
                f"last_name.{padding}": {"raw_text": "Hewitt", "confidence": 0.85}
                for padding in (0, 2, 4)
            }
        )

        self.extractor.refine_name_fields(self.image, self.tokens, self.fields)

        reading = self.fields["last_name"]
        self.assertEqual(reading["raw_text"], "Hewitt")
        self.assertEqual(reading["initial_reading"]["raw_text"], "HewittO")
        self.assertEqual(reading["full_image_reading"], "Hewitt")

    def test_enlarged_name_crops_keep_the_two_reading_confidence_requirement(self):
        low = {
            f"last_name.{padding}": {"raw_text": "Hewitt", "confidence": 0.78}
            for padding in (0, 2, 4)
        }
        high = {
            f"last_name.{padding}": {"raw_text": "Hewitt", "confidence": 0.87}
            for padding in (0, 2, 4)
        }
        self.extractor.recognize = Mock(side_effect=[low, high])

        self.extractor.refine_name_fields(self.image, self.tokens, self.fields)

        reading = self.fields["last_name"]
        self.assertEqual(reading["raw_text"], "Hewitt")
        self.assertEqual(reading["initial_reading"]["raw_text"], "HewittO")
        self.assertEqual(len(reading["name_retry"]), 6)
        enlarged = self.extractor.recognize.call_args_list[1].args[0]
        self.assertEqual(enlarged.size, (2732, 1536))

    def test_disagreeing_or_low_confidence_name_retry_is_not_used(self):
        for text, confidence in (("HewittO", 0.99), ("Hewitt", 0.74), ("Hewitt", 0.81)):
            with self.subTest(text=text, confidence=confidence):
                fields = dict(self.fields)
                self.extractor.recognize = Mock(
                    return_value={
                        f"last_name.{padding}": {
                            "raw_text": text,
                            "confidence": confidence,
                        }
                        for padding in (0, 2, 4)
                    }
                )

                self.extractor.refine_name_fields(self.image, self.tokens, fields)

                self.assertEqual(fields["last_name"]["raw_text"], "HewittO")
                self.assertNotIn("initial_reading", fields["last_name"])

    def test_one_agreeing_crop_is_not_enough_to_change_a_name(self):
        self.extractor.recognize = Mock(
            return_value={
                "last_name.0": {"raw_text": "Hewitt", "confidence": 0.99},
                "last_name.2": {"raw_text": "HewittO", "confidence": 0.99},
                "last_name.4": {"raw_text": "HewittO", "confidence": 0.99},
            }
        )

        self.extractor.refine_name_fields(self.image, self.tokens, self.fields)

        self.assertEqual(self.fields["last_name"]["raw_text"], "HewittO")
        self.assertNotIn("initial_reading", self.fields["last_name"])

    def test_unrelated_or_low_confidence_detected_names_are_not_used(self):
        outside = ocr_tokens([("Hewitt", 700, 270, 800, 300)])
        uncertain = [{**token, "confidence": 0.69} for token in self.tokens]
        for tokens in (outside, uncertain):
            with self.subTest(tokens=tokens):
                fields = dict(self.fields)
                self.extractor.recognize = Mock()

                self.extractor.refine_name_fields(self.image, tokens, fields)

                self.assertEqual(fields["last_name"]["raw_text"], "HewittO")
                self.extractor.recognize.assert_not_called()


class NonMatchExtractionTests(unittest.TestCase):
    def setUp(self):
        self.extractor = ScreenshotExtractor(engine=object())

    def transfer_tokens(self, status="Accepted", completion=None):
        return ocr_tokens(
            [
                ("CONTRACT OFFERS", 688, 202, 803, 219),
                ("Test", 703, 233, 761, 254),
                ("Player", 702, 256, 862, 286),
                ("Notts County", 735, 289, 808, 308),
                ("$5,900", 698, 358, 744, 376),
                ("3 Year(s]", 818, 358, 870, 376),
                (
                    completion
                    if completion is not None
                    else "We have agreed terms with Test Player and he just joined the team.",
                    687,
                    392,
                    1011,
                    409,
                ),
                ("$5,900", 756, 523, 802, 547),
                (status, 869, 529, 918, 546),
                ("Transfer", 966, 530, 1013, 545),
                ("Other Player", 332, 274, 440, 296),
                ("17/07", 596, 274, 641, 296),
                ("T. Player", 332, 385, 410, 405),
                ("03/08", 596, 385, 641, 405),
            ]
        )

    def test_contract_wage_is_not_a_transfer_fee(self):
        records, fields, issues = self.extractor.extract_transfer(
            self.transfer_tokens()
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["player"], "Test Player")
        self.assertEqual(records[0]["transfer_type"], "permanent")
        self.assertEqual(records[0]["weekly_wage_minor"], 590000)
        self.assertEqual(records[0]["contract_months"], 36)
        self.assertIsNone(records[0]["fee_minor"])
        self.assertIsNone(records[0]["loan_months"])
        self.assertIsNone(records[0]["effective_on"])
        self.assertNotIn("17/07", records[0]["date_basis"])
        self.assertIn("completion", fields)
        self.assertTrue(issues)

    def test_pending_and_rejected_offers_are_not_signings(self):
        for status, completion in (
            ("Rejected", None),
            ("Pending", None),
        ):
            with self.subTest(status=status, completion=completion):
                records, fields, issues = self.extractor.extract_transfer(
                    self.transfer_tokens(status, completion)
                )
                self.assertEqual(records, [])
                self.assertTrue(issues)

    def test_accepted_transfers_use_the_user_confirmed_completion_rule(self):
        for completion in (
            "We have accepted the offer and will negotiate a contract.",
            "He has not joined the team.",
            "",
        ):
            with self.subTest(completion=completion):
                records, fields, issues = self.extractor.extract_transfer(
                    self.transfer_tokens("Accepted", completion)
                )
                self.assertEqual(len(records), 1)
                self.assertIn(
                    "User-confirmed archive rule", records[0]["context_basis"]
                )
                self.assertIsNone(records[0]["effective_on"])
                self.assertEqual(fields["completion"]["raw_text"], completion)

    def news_tokens(
        self,
        headline="King grabs August Player of the Month Award",
        body=None,
        matching_date="05/09/2018",
    ):
        return ocr_tokens(
            [
                (headline, 955, 232, 1250, 279),
                (
                    body
                    if body is not None
                    else "King's impressive performance for Notts County earned him the EFL League Two award.",
                    955,
                    304,
                    1238,
                    344,
                ),
                ("Notts County Crowned EFL League One Champions", 105, 210, 353, 239),
                ("05/10/2019", 105, 251, 187, 266),
                (headline, 105, 358, 352, 396),
                (matching_date, 105, 399, 187, 416),
            ]
        )

    def test_senior_contract_email_requires_dated_acceptance(self):
        accepted = "I'm very happy to accept your contract offer with the senior team."
        for date_text, subject, body, expected in (
            ("03/02/2021", "[info] Contract Accepted", accepted, True),
            ("", "[info] Contract Accepted", accepted, False),
            ("03/02/2021", "[info] Contract Rejected", accepted, False),
            (
                "03/02/2021",
                "[info] Contract Accepted",
                "I need more time to decide.",
                False,
            ),
        ):
            with self.subTest(date=date_text, subject=subject, body=body):
                tokens = ocr_tokens(
                    [
                        ("Notts County", 151, 89, 262, 106),
                        (date_text, 802, 218, 908, 235),
                        ("Test Player", 802, 241, 949, 259),
                        ("Kedia, Mr.", 802, 260, 914, 276),
                        (subject, 802, 294, 1093, 315),
                        (body, 705, 391, 1259, 432),
                        ("Other Player", 156, 208, 339, 229),
                    ]
                )
                records, _fields, _issues = self.extractor.extract_inbox(tokens)
                if not expected:
                    self.assertEqual(records, [])
                    continue
                self.assertEqual(len(records), 1)
                record = records[0]
                self.assertEqual(record["player"], "Test Player")
                self.assertEqual(record["to_club"], "Notts County")
                self.assertEqual(record["transfer_type"], "permanent")
                self.assertEqual(record["effective_on"], "2021-02-03")
                for field in (
                    "from_club",
                    "fee_minor",
                    "weekly_wage_minor",
                    "contract_months",
                ):
                    self.assertIsNone(record.get(field))

    def test_news_date_comes_from_matching_headline_not_first_story(self):
        records, fields, issues = self.extractor.extract_news(self.news_tokens())
        award = next(
            record
            for record in records
            if record["event_type"] == "player_of_the_month"
        )
        self.assertEqual(award["announced_on"], "2018-09-05")
        self.assertEqual(award["competition"], "EFL League Two")
        self.assertEqual(award["club"], "Notts County")
        self.assertEqual(
            sum(record["event_type"] == "player_of_the_month" for record in records), 1
        )
        self.assertIn("news.2.announced_on", fields)

    def test_transfer_rumour_is_news_not_an_assist_snapshot_or_completed_transfer(self):
        for body, expected in (
            (
                (
                    "Few players are more in demand than Notts County's Test Player. "
                    "He currently leads the league in assists with 12. "
                    "Racing Club have reportedly approached Notts County."
                ),
                True,
            ),
            ("Racing Club could offer $12,000,000 for the player.", False),
        ):
            with self.subTest(body=body):
                records, _fields, _issues = self.extractor.extract_news(
                    ocr_tokens(
                        [
                            (
                                "Assist Leader Test Player Targeted by",
                                955,
                                232,
                                1260,
                                250,
                            ),
                            ("Racing Club", 955, 265, 1170, 283),
                            (body, 955, 312, 1260, 490),
                        ]
                    )
                )
                if not expected:
                    self.assertEqual(records, [])
                    continue
                self.assertEqual(len(records), 1)
                record = records[0]
                self.assertEqual(record["type"], "competition_event")
                self.assertEqual(record["event_type"], "transfer_interest")
                self.assertEqual(record["player"], "Test Player")
                self.assertEqual(record["club"], "Notts County")
                self.assertNotIn("assists", record)
                self.assertNotIn("transfer_type", record)
                self.assertIn("Transfer interest only", record["description"])
                for field in (
                    "competition",
                    "season",
                    "observed_on",
                    "appearances",
                    "goals",
                ):
                    self.assertIsNone(record.get(field))

    def test_unknown_news_date_is_not_replaced_with_neighbor_date(self):
        records, fields, issues = self.extractor.extract_news(
            self.news_tokens(matching_date="NEW!")
        )
        award = next(
            record
            for record in records
            if record["event_type"] == "player_of_the_month"
        )
        self.assertIsNone(award["announced_on"])
        self.assertIsNone(award["season"])
        self.assertEqual(award["period"], "August")

    def test_other_article_does_not_supply_golden_boot_competition(self):
        records, fields, issues = self.extractor.extract_news(
            self.news_tokens("King Wins Golden Boot", body="")
        )
        award = next(
            record for record in records if record["event_type"] == "golden_boot"
        )
        self.assertEqual(award["player"], "King")
        self.assertIsNone(award["competition"])
        self.assertIsNone(award["club"])
        self.assertTrue(
            any("Competition or season is not stated" in issue for issue in issues)
        )

    def test_unselected_golden_boot_headline_does_not_create_a_player_event(self):
        tokens = self.news_tokens() + ocr_tokens(
            [
                ("Zoko Wins Golden Boot", 105, 435, 353, 461),
                ("04/05/2019", 105, 475, 187, 490),
            ]
        )
        records, fields, _issues = self.extractor.extract_news(tokens)
        self.assertTrue(any(record["player"] == "King" for record in records))
        self.assertFalse(
            any(record["event_type"] == "golden_boot" for record in records)
        )
        self.assertIn("Zoko", fields["news.3.title"]["raw_text"])

    def dashboard_award(self, headlines, calendar="DEC 2019", fixture_date=""):
        self.extractor.recognize = Mock(
            side_effect=lambda image, regions: {
                field: {"raw_text": "", "confidence": 0.0} for field in regions
            }
        )
        tokens = ocr_tokens(
            [
                (calendar, 600, 210, 670, 230),
                (fixture_date, 90, 249, 370, 268),
                ("EFL League One", 420, 360, 610, 385),
                ("Notts County", 430, 460, 620, 480),
                ("Tosin Adarabioyo", 1000, 535, 1160, 575),
                *headlines,
            ]
        )
        return self.extractor.extract_dashboard_award(
            Image.new("RGB", (1366, 768), "white"), tokens
        )

    def test_dashboard_annual_winner_uses_only_the_news_tile(self):
        records, _fields, _issues = self.dashboard_award(
            [
                ("Player of the Year Announced", 782, 444, 917, 457),
                ("Lionel Messi", 925, 441, 1028, 457),
            ]
        )
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["event_type"], "player_of_the_year")
        self.assertEqual(record["player"], "Lionel Messi")
        self.assertEqual(record["period"], "2019")
        self.assertIn("2019-12", record["context_basis"])
        for field in ("club", "competition", "season", "announced_on"):
            self.assertIsNone(record[field])

    def test_dashboard_champion_can_use_a_raised_headline(self):
        records, _fields, _issues = self.dashboard_award(
            [("Notts County Crowned EFL League Two Champions", 709, 393, 1280, 413)],
            calendar="MAY 2019",
        )
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["event_type"], "champion")
        self.assertEqual(record["club"], "Notts County")
        self.assertEqual(record["competition"], "EFL League Two")
        self.assertEqual(record["season"], "2018/19")
        self.assertIsNone(record["player"])
        self.assertIsNone(record["announced_on"])

    def test_unnamed_annual_award_does_not_use_the_training_player(self):
        records, _fields, _issues = self.dashboard_award(
            [("Player of the Year Announced", 782, 444, 917, 457)]
        )
        self.assertEqual(records, [])

    def test_raised_headline_crop_recovers_a_missing_detected_line(self):
        self.extractor.recognize = Mock(
            side_effect=[
                {"headline": {"raw_text": "", "confidence": 0.0}},
                {
                    "headline.raised": {
                        "raw_text": "Notts County Crowned EFL League Two Champions",
                        "confidence": 0.99,
                    }
                },
            ]
        )
        records, fields, _issues = self.extractor.extract_dashboard_award(
            Image.new("RGB", (1366, 768), "white"),
            ocr_tokens([("MAY 2019", 600, 210, 670, 230)]),
        )
        self.assertEqual(records[0]["club"], "Notts County")
        self.assertEqual(records[0]["season"], "2018/19")
        self.assertIn("headline.raised", fields)

    def test_conflicting_or_missing_dashboard_dates_do_not_invent_award_years(self):
        for calendar, fixture in (("DEC 2019", "January 2020"), ("", "")):
            with self.subTest(calendar=calendar, fixture=fixture):
                records, _fields, _issues = self.dashboard_award(
                    [
                        (
                            "Player of the Year Announced Lionel Messi",
                            782,
                            442,
                            1030,
                            459,
                        )
                    ],
                    calendar=calendar,
                    fixture_date=fixture,
                )
                self.assertIsNone(records[0]["period"])
                self.assertIsNone(records[0]["announced_on"])


@unittest.skipUnless(
    os.environ.get("CAREER_OCR_TESTS") == "1",
    "Set CAREER_OCR_TESTS=1 for real-image OCR checks",
)
class ScreenshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.extractor = ScreenshotExtractor()
        cls.root = Path(__file__).resolve().parents[2]

    def extract(self, sequence, method, **kwargs):
        with Image.open(self.root / "raw_screenshots" / f"{sequence}.png") as image:
            return method(image.convert("RGB"), **kwargs)[0]

    def test_preseason_score_and_team_stats(self):
        record = self.extract(4, self.extractor.extract_match)
        self.assertEqual((record["home_goals"], record["away_goals"]), (1, 1))
        self.assertEqual(record["competition"], "European International Cup")
        self.assertEqual(record["team_stats"]["home"]["shots"], 6)
        self.assertEqual(record["team_stats"]["away"]["fouls"], 0)

    def test_outfield_zeroes_and_passing(self):
        record = self.extract(7, self.extractor.extract_player)
        self.assertEqual(record["player"], "Takefusa Kubo")
        self.assertEqual(record["goals"], 0)
        self.assertEqual(record["assists"], 1)
        self.assertEqual(record["rating"], 8.4)
        self.assertEqual(
            [
                record[f"passes_completed_{distance}"]
                for distance in ("short", "medium", "long")
            ],
            [13, 3, 0],
        )
        self.assertEqual(record["possession_lost"], 10)

    def test_goalkeeper_layout(self):
        record = self.extract(26, self.extractor.extract_player, goalkeeper=True)
        self.assertEqual(record["player"], "Aaron Ramsdale")
        self.assertEqual(record["goals_conceded"], 0)
        self.assertEqual(record["shots_caught"], 4)
        self.assertEqual(record["shots_parried"], 2)
        self.assertEqual(record["crosses_caught"], 1)
        self.assertNotIn("goals", record)

    def test_november_single_digit_stats_are_not_missing(self):
        keeper = self.extract(1301, self.extractor.extract_player, goalkeeper=True)
        self.assertEqual(keeper["player"], "Frederik Schram")
        self.assertEqual(keeper["assists"], 0)
        for sequence, played_on in ((1296, "2019-11-12"), (1309, "2019-11-16")):
            with self.subTest(sequence=sequence):
                match = self.extract(sequence, self.extractor.extract_match)
                self.assertEqual(match["played_on"], played_on)
                self.assertEqual(match["team_stats"]["home"]["corners"], 1)
                self.assertEqual(match["team_stats"]["away"]["corners"], 1)
                self.assertIsNotNone(match["team_stats"]["away"]["fouls"])

    def test_remaining_warning_screens_have_numeric_values(self):
        for sequence in (
            1312,
            1329,
            1341,
            1357,
            1372,
            1388,
            1400,
            1413,
            1426,
            1444,
            1458,
            1459,
        ):
            with self.subTest(goalkeeper=sequence):
                player = self.extract(
                    sequence, self.extractor.extract_player, goalkeeper=True
                )
                self.assertEqual(player["assists"], 0)
                self.assertEqual(player["clearances"], 0)
        fields = (
            "shots",
            "shots_on_target",
            "possession_pct",
            "tackles",
            "fouls",
            "corners",
            "shot_accuracy_pct",
            "pass_accuracy_pct",
        )
        expected = {
            1324: ((5, 1, 47, 5, 1, 1, 20, 88), (4, 3, 53, 10, 0, 0, 75, 90)),
            1339: ((7, 4, 44, 6, 2, 1, 57, 86), (6, 2, 56, 2, 0, 2, 33, 78)),
            1354: ((12, 7, 57, 5, 1, 4, 58, 85), (5, 3, 43, 11, 2, 1, 60, 83)),
            1367: ((4, 0, 47, 6, 0, 2, 0, 87), (8, 5, 53, 6, 0, 1, 62, 86)),
            1381: ((6, 3, 52, 7, 0, 5, 50, 71), (1, 1, 48, 3, 0, 0, 100, 85)),
            1408: ((2, 1, 52, 6, 0, 1, 50, 91), (4, 2, 48, 6, 1, 2, 50, 80)),
            1424: ((8, 2, 51, 7, 1, 0, 25, 88), (9, 5, 49, 12, 1, 0, 55, 91)),
            1439: ((7, 5, 41, 5, 2, 2, 71, 82), (10, 8, 59, 5, 2, 1, 80, 84)),
            1454: ((2, 2, 45, 6, 0, 0, 100, 82), (3, 1, 55, 7, 3, 1, 33, 80)),
        }
        for sequence, values in expected.items():
            with self.subTest(match=sequence):
                match = self.extract(sequence, self.extractor.extract_match)
                for side, expected_stats in zip(("home", "away"), values):
                    self.assertEqual(
                        match["team_stats"][side], dict(zip(fields, expected_stats))
                    )

    def test_name_readings_agree_with_detected_tight_crops(self):
        for sequence, expected, refined in (
            (31, "Elliott Hewitt", True),
            (352, "Elliott Hewitt", True),
            (914, "Leo Ostigard", True),
            (1292, "Leo Ostigard", False),
            (2508, "George Baker", True),
        ):
            with self.subTest(sequence=sequence):
                extraction = self.extractor.extract(
                    self.root / "raw_screenshots" / f"{sequence}.png"
                )
                self.assertTrue(extraction["records"])
                self.assertEqual(
                    {record["player"] for record in extraction["records"]}, {expected}
                )
                reading = extraction["evidence"]["fields"]["last_name"]
                self.assertEqual(
                    reading["method"],
                    "rapidocr_detected_name_consensus"
                    if refined
                    else "rapidocr_recognizer_crop",
                )
                self.assertEqual("initial_reading" in reading, refined)

    def test_squad_overall_snapshots(self):
        first = self.extract(1, self.extractor.extract_snapshot)
        last = self.extract(908, self.extractor.extract_snapshot)
        self.assertEqual((first["overall"], last["overall"]), (62, 65))
        self.assertEqual(first["player"], last["player"])
        self.assertIsNone(first["observed_on"])

    def test_season_totals_remain_separate_from_match_stats(self):
        with Image.open(self.root / "raw_screenshots/909.png") as image:
            records, evidence = self.extractor.extract_squad_totals(
                image.convert("RGB")
            )
        total = next(
            record for record in records if record["scope"] == "all_competitions"
        )
        self.assertEqual(total["type"], "player_competition_snapshot")
        self.assertEqual(total["player"], "Erling Braut Haaland")
        self.assertEqual(
            (total["appearances"], total["goals"], total["assists"]), (52, 23, 13)
        )
        self.assertEqual(total["average_rating"], 7.7)
        self.assertIsNone(total["season"])
        self.assertNotIn("match_id", total)
        self.assertIn("season_totals.5.goals", evidence)

    def test_season_table_detection_survives_misread_heading(self):
        extraction = self.extractor.extract(self.root / "raw_screenshots/924.png")
        records = [
            record
            for record in extraction["records"]
            if record["type"] == "player_competition_snapshot"
        ]
        self.assertEqual(len(records), 6)
        self.assertEqual(records[0]["player"], "Elliott Hewitt")

    def test_completed_loan_preserves_terms_without_inventing_a_date_or_fee(self):
        extraction = self.extractor.extract(self.root / "raw_screenshots/1084.png")
        self.assertEqual(
            [record["type"] for record in extraction["records"]], ["player_transfer"]
        )
        record = extraction["records"][0]
        self.assertEqual(record["player"], "Dominic Calvert-Lewin")
        self.assertEqual(record["transfer_type"], "loan")
        self.assertEqual(record["to_club"], "Notts County")
        self.assertEqual((record["contract_months"], record["loan_months"]), (12, 24))
        self.assertIsNone(record["effective_on"])
        self.assertIsNone(record["fee_minor"])

    def test_completed_permanent_transfers(self):
        for sequence, player, wage, months in (
            (977, "Matty James", 3599900, 24),
            (1011, "Tosin Adarabioyo", 590000, 36),
        ):
            with self.subTest(sequence=sequence):
                extraction = self.extractor.extract(
                    self.root / "raw_screenshots" / f"{sequence}.png"
                )
                self.assertEqual(len(extraction["records"]), 1)
                record = extraction["records"][0]
                self.assertEqual(record["player"], player)
                self.assertEqual(record["transfer_type"], "permanent")
                self.assertEqual(record["weekly_wage_minor"], wage)
                self.assertEqual(record["contract_months"], months)
                self.assertIsNone(record["fee_minor"])

    def test_player_of_the_month_articles_and_headlines(self):
        for sequence, player, period, announced_on, competition in (
            (183, "King", "2018-08", "2018-09-05", "EFL League Two"),
            (257, "King", "2018-09", "2018-10-05", "EFL League Two"),
            (1207, "Calvert-Lewin", "2019-09", "2019-10-05", None),
        ):
            with self.subTest(sequence=sequence):
                extraction = self.extractor.extract(
                    self.root / "raw_screenshots" / f"{sequence}.png"
                )
                self.assertEqual(len(extraction["records"]), 1)
                record = extraction["records"][0]
                self.assertEqual(record["event_type"], "player_of_the_month")
                self.assertEqual(record["player"], player)
                self.assertEqual(record["period"], period)
                self.assertEqual(record["announced_on"], announced_on)
                self.assertEqual(record["competition"], competition)

    def test_player_and_goalkeeper_competition_awards(self):
        player = self.extractor.extract(self.root / "raw_screenshots/81.png")[
            "records"
        ][0]
        self.assertEqual(
            (player["event_type"], player["player"]),
            ("player_of_the_competition", "Haaland"),
        )
        self.assertEqual(
            (player["club"], player["competition"]),
            ("Notts County", "European International Cup"),
        )
        self.assertEqual(player["announced_on"], "2018-07-18")
        records = self.extractor.extract(self.root / "raw_screenshots/906.png")[
            "records"
        ]
        by_type = {record["event_type"]: record for record in records}
        self.assertEqual(len(records), 2)
        self.assertEqual(
            by_type["goalkeeper_of_the_competition"]["player"], "Aaron Ramsdale"
        )
        self.assertEqual(
            by_type["goalkeeper_of_the_competition"]["club"], "Notts County"
        )
        self.assertEqual(by_type["champion"]["competition"], "EFL League Two")
        self.assertEqual(by_type["champion"]["club"], "Notts County")
        self.assertNotIn("golden_boot", by_type)
        self.assertFalse(any(record.get("player") == "Zoko" for record in records))

    def test_tournament_winner_does_not_invent_a_fixture_or_season(self):
        extraction = self.extractor.extract(self.root / "raw_screenshots/80.png")
        self.assertEqual(len(extraction["records"]), 1)
        record = extraction["records"][0]
        self.assertEqual(record["type"], "competition_event")
        self.assertEqual(record["event_type"], "champion")
        self.assertEqual(record["club"], "Notts County")
        self.assertEqual(record["competition"], "European International Cup")
        self.assertIsNone(record["season"])
        self.assertIsNone(record["announced_on"])

    def test_dashboard_award_banners_do_not_borrow_match_or_training_details(self):
        for sequence, player, period in (
            (677, "Williams", "2019-01"),
            (720, "Haaland", "2019-02"),
            (813, "Haaland", "2019-03"),
            (1116, "Kubo", "2019-08"),
        ):
            with self.subTest(sequence=sequence):
                extraction = self.extractor.extract(
                    self.root / "raw_screenshots" / f"{sequence}.png"
                )
                self.assertEqual(extraction["screen_type"], "dashboard_award")
                self.assertEqual(len(extraction["records"]), 1)
                record = extraction["records"][0]
                self.assertEqual((record["player"], record["period"]), (player, period))
                self.assertIsNone(record["announced_on"])
                self.assertIsNone(record["competition"])
                self.assertIsNone(record["club"])

    def test_annotated_championship_and_annual_award_banners(self):
        for sequence, expected in (
            (
                907,
                {
                    "event_type": "champion",
                    "club": "Notts County",
                    "competition": "EFL League Two",
                    "season": "2018/19",
                    "period": "2018/19",
                    "player": None,
                },
            ),
            (
                1393,
                {
                    "event_type": "player_of_the_year",
                    "player": "Lionel Messi",
                    "period": "2019",
                    "competition": None,
                    "club": None,
                    "season": None,
                },
            ),
        ):
            with self.subTest(sequence=sequence):
                extraction = self.extractor.extract(
                    self.root / "raw_screenshots" / f"{sequence}.png"
                )
                self.assertEqual(extraction["screen_type"], "dashboard_award")
                self.assertEqual(len(extraction["records"]), 1)
                record = extraction["records"][0]
                for field, value in expected.items():
                    self.assertEqual(record[field], value, field)
                self.assertIsNone(record["announced_on"])


if __name__ == "__main__":
    unittest.main()
