import os
import tempfile
import unittest
from pathlib import Path

from processing.database import connect, insert_entity
from processing.extraction import ScreenshotExtractor, club_name, parse_profile_details
from processing.identifiers import normalize_references
from processing.normalization import (
    FIFA19_COUNTRIES,
    FIFA19_SOURCE,
    canonical_club_name,
    normalize_nationality,
    normalize_positions,
    resolve_nationality,
)
from processing.pipeline import ensure_club, ensure_player

CLUB_CASES = (
    ("Lincolncity", "Lincoln City"),
    ("Crawleytown", "Crawley Town"),
    ("Swindontown", "Swindon Town"),
    ("Portvale", "Port Vale"),
    ("Grimsbytown", "Grimsby Town"),
    ("..Doncaster", "Doncaster"),
    ("Coventrycity", "Coventry City"),
)


class IdentityParsingTests(unittest.TestCase):
    def test_reported_profile_lines(self):
        for raw, position, age, country in (
            ("● GK IAge 24 I+ Iceland ", "GK", 24, "Iceland"),
            ("● CB I Age 19 IH Norway", "CB", 19, "Norway"),
            ("● CB I Age 31 IX Scotand", "CB", 31, "Scotland"),
            ("● RM/ST I Age 28 IE England", "RM/ST", 28, "England"),
            ("● CAM/RM/ST/LM I Age 17 ID Japan", "CAM/RM/ST/LM", 17, "Japan"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(
                    parse_profile_details(raw),
                    {
                        "displayed_position": position,
                        "age": age,
                        "nationality": country,
                    },
                )

    def test_all_fifa19_countries_and_common_noise(self):
        for country in FIFA19_COUNTRIES:
            with self.subTest(country=country):
                self.assertEqual(normalize_nationality(country), country)
                self.assertEqual(normalize_nationality(" | " + country), country)
        self.assertEqual(normalize_nationality("Age 25 1 South Africa"), "South Africa")
        self.assertEqual(normalize_nationality("ge 17 Ip Japan"), "Japan")
        self.assertIsNone(normalize_nationality("CB | Age: 21 England"))
        self.assertEqual(
            normalize_nationality("Republic of Ireland"), "Republic of Ireland"
        )
        self.assertEqual(normalize_nationality("DR Congo"), "DR Congo")
        self.assertIsNone(normalize_nationality("Unrelated England"))
        self.assertIsNone(normalize_nationality("Deep England"))
        self.assertIsNone(normalize_nationality("Narnia"))
        self.assertIsNone(normalize_nationality(""))
        with self.assertRaises(ValueError):
            normalize_nationality(1)

    def test_position_cleanup_and_partial_profiles(self):
        self.assertEqual(normalize_positions("GK I"), "GK")
        self.assertEqual(normalize_positions(" ● LW / RW / CAM / LM |"), "LW/RW/CAM/LM")
        self.assertIsNone(normalize_positions("Something GK"))
        self.assertEqual(
            parse_profile_details("GK | Age 24 unreadable"),
            {
                "displayed_position": "GK",
                "age": 24,
            },
        )
        self.assertEqual(parse_profile_details("No profile here"), {})

    def test_club_variants_canonicalize_without_merging_unrelated_names(self):
        for raw, canonical in CLUB_CASES:
            for value in (raw, canonical, "  " + raw.upper() + "  "):
                with self.subTest(value=value):
                    self.assertEqual(canonical_club_name(value), canonical)
                    self.assertEqual(club_name(value), canonical)
        self.assertEqual(canonical_club_name("Doncaster Rovers"), "Doncaster Rovers")
        self.assertEqual(canonical_club_name("Lincoln United"), "Lincoln United")
        self.assertEqual(canonical_club_name("Other   Club"), "Other Club")
        self.assertIsNone(club_name("   "))

    def test_verified_fifa19_fallback_is_exact_and_source_values_win(self):
        for name, country, fifa_id in (
            ("Matty James", "England", 186139),
            ("Tosin Adarabioyo", "England", 222104),
            ("Dominic Calvert-Lewin", "England", 221479),
            ("Seydou Doumbia", "Ivory Coast", 188428),
            ("Sammy Ameobi", "England", 203537),
            ("Thiago Almada", "Argentina", 245371),
            ("Abdoulaye Dabo", "France", 241403),
            ("Lionel Messi", "Argentina", 158023),
        ):
            with self.subTest(name=name):
                resolved, basis = resolve_nationality(name)
                self.assertEqual(resolved, country)
                self.assertEqual(basis["fifa19_id"], fifa_id)
                self.assertEqual(basis["source"], FIFA19_SOURCE)
                self.assertEqual(resolve_nationality(name, country), (country, None))
        self.assertEqual(resolve_nationality("Matty James", "Canada"), ("Canada", None))
        self.assertEqual(resolve_nationality("M. James"), (None, None))
        self.assertEqual(resolve_nationality("James"), (None, None))
        self.assertEqual(resolve_nationality("Zoko"), (None, None))
        self.assertEqual(resolve_nationality("Unknown Player"), (None, None))

    def test_user_confirmed_name_exceptions(self):
        for name, country in (
            ("Leo Ostigard", "Norway"),
            ("Scott Cuthbert", "Scotland"),
            ("Nathan Delfouneso", "England"),
            ("Takefusa Kubo", "Japan"),
        ):
            self.assertEqual(resolve_nationality(name, "unreadable")[0], country)


class IdentityImportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.connection = connect(Path(self.directory.name) / "career.sqlite")
        self.addCleanup(self.connection.close)

    def test_club_alias_order_does_not_create_duplicates(self):
        for raw, canonical in CLUB_CASES:
            with self.subTest(club=canonical):
                first = ensure_club(self.connection, raw)
                self.assertEqual(ensure_club(self.connection, canonical), first)
                self.assertEqual(ensure_club(self.connection, "  " + raw + "  "), first)
                self.assertEqual(
                    self.connection.execute(
                        "SELECT name FROM clubs WHERE id=?", (first,)
                    ).fetchone()[0],
                    canonical,
                )
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM clubs").fetchone()[0], 7
        )

    def test_existing_variant_keeps_its_id_and_alias(self):
        existing = insert_entity(self.connection, "clubs", {"name": "Lincolncity"})
        self.assertEqual(ensure_club(self.connection, "Lincoln City"), existing)
        self.assertEqual(ensure_club(self.connection, "Lincolncity"), existing)
        self.assertEqual(
            self.connection.execute(
                "SELECT name FROM clubs WHERE id=?", (existing,)
            ).fetchone()[0],
            "Lincoln City",
        )

    def test_legacy_duplicates_require_rebuild_instead_of_silent_relinking(self):
        insert_entity(self.connection, "clubs", {"name": "Coventry City"})
        insert_entity(self.connection, "clubs", {"name": "Coventrycity"})
        with self.assertRaisesRegex(ValueError, "Duplicate club identity"):
            ensure_club(self.connection, "Coventry City")
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM clubs").fetchone()[0], 2
        )

    def test_missing_nationality_gets_verified_fallback_without_overwriting_known_data(
        self,
    ):
        player_id = ensure_player(self.connection, {"player": "Lionel Messi"})
        self.assertEqual(
            self.connection.execute(
                "SELECT nationality FROM players WHERE id=?", (player_id,)
            ).fetchone()[0],
            "Argentina",
        )
        player_id = ensure_player(
            self.connection, {"player": "Matty James", "nationality": "Canada"}
        )
        ensure_player(self.connection, {"player": "Matty James"})
        self.assertEqual(
            self.connection.execute(
                "SELECT nationality FROM players WHERE id=?", (player_id,)
            ).fetchone()[0],
            "Canada",
        )
        with self.assertRaisesRegex(ValueError, "Conflicting nationality"):
            ensure_player(
                self.connection, {"player": "Matty James", "nationality": "England"}
            )

    def test_existing_ocr_noise_is_cleaned_and_unknown_values_are_not_saved(self):
        player_id = insert_entity(
            self.connection,
            "players",
            {"name": "Scott Cuthbert", "nationality": "IX Scotand"},
        )
        ensure_player(
            self.connection, {"player_id": player_id, "player": "Scott Cuthbert"}
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT nationality FROM players WHERE id=?", (player_id,)
            ).fetchone()[0],
            "Scotland",
        )
        unknown = ensure_player(
            self.connection, {"player": "Unknown Player", "nationality": "Narnia"}
        )
        self.assertIsNone(
            self.connection.execute(
                "SELECT nationality FROM players WHERE id=?", (unknown,)
            ).fetchone()[0]
        )

    def test_external_provenance_does_not_get_treated_as_an_internal_uuid(self):
        _, basis = resolve_nationality("Lionel Messi")
        value = {"nationality_basis": basis}
        self.assertEqual(normalize_references(self.connection, value), value)


@unittest.skipUnless(
    os.environ.get("CAREER_OCR_TESTS") == "1",
    "Set CAREER_OCR_TESTS=1 for real-image checks",
)
class IdentityScreenshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.extractor = ScreenshotExtractor()
        cls.root = Path(__file__).resolve().parents[2] / "raw_screenshots"

    def test_five_reported_profile_errors(self):
        for number, field, expected in (
            (911, "displayed_position", "GK"),
            (914, "nationality", "Norway"),
            (915, "nationality", "Scotland"),
            (921, "nationality", "England"),
            (925, "nationality", "Japan"),
        ):
            with self.subTest(screenshot=number):
                result = self.extractor.extract(self.root / f"{number}.png")
                self.assertEqual(result["records"][0][field], expected)

    def test_transfer_nationality_and_news_reference_provenance(self):
        transfer = self.extractor.extract(self.root / "1084.png")
        self.assertEqual(transfer["records"][0]["nationality"], "England")
        self.assertIn("profile_details", transfer["evidence"]["fields"])
        news = self.extractor.extract(self.root / "1393.png")
        self.assertEqual(news["records"][0]["nationality"], "Argentina")
        self.assertEqual(news["records"][0]["nationality_basis"]["fifa19_id"], 158023)
        self.assertTrue(news["evidence"]["nationality_fallbacks"])

    def test_doncaster_header(self):
        result = self.extractor.extract(self.root / "1309.png")
        self.assertEqual(result["records"][0]["home_club"], "Doncaster")


if __name__ == "__main__":
    unittest.main()
