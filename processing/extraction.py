import re
from datetime import date
from decimal import Decimal

import numpy as np
from PIL import Image, ImageOps

from . import EXTRACTOR_VERSION
from .normalization import (
    POSITIONS,
    canonical_club_name,
    canonical_venue_name,
    normalize_nationality,
    normalize_positions,
    resolve_nationality,
)
from .vocabulary import split_joined_words

BASE_WIDTH = 1366
BASE_HEIGHT = 768
COMPETITION_LABELS = {
    "europeanintlcup": "European International Cup",
    "europeaninternationalcup": "European International Cup",
    "invitationalcup": "Invitational Cup",
    "eflleaguetwo": "EFL League Two",
    "eflleagueone": "EFL League One",
    "premierleague": "Premier League",
    "champplayoffs": "EFL Championship Play-Offs",
    "champplayffs": "EFL Championship Play-Offs",
    "championshipplayoffs": "EFL Championship Play-Offs",
    "eflchampionship": "EFL Championship",
    "uefachampionsleague": "UEFA Champions League",
    "uefaeuropaleague": "UEFA Europa League",
    "lgtwoplayoffs": "EFL League Two Play-Offs",
    "lgoneplayoffs": "EFL League One Play-Offs",
    "carabaocup": "Carabao Cup",
    "checkatradetrophy": "Checkatrade Trophy",
    "theemiratesfacup": "FA Cup",
}
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
TEAM_ROWS = {
    "shots": 330,
    "shots_on_target": 366,
    "possession_pct": 401,
    "tackles": 437,
    "fouls": 472,
    "corners": 508,
    "shot_accuracy_pct": 543,
    "pass_accuracy_pct": 579,
}
OUTFIELD_ROWS = {
    "goals": ("left", 358),
    "shots_on_target/shots_off_target": ("left", 384),
    "assists": ("left", 435),
    "passes_completed_short/passes_completed_medium/passes_completed_long": (
        "left",
        460,
    ),
    "passes_failed_short/passes_failed_medium/passes_failed_long": ("left", 486),
    "key_passes": ("left", 512),
    "crosses_successful/crosses_failed": ("left", 537),
    "key_dribbles": ("left", 588),
    "fouled": ("left", 614),
    "successful_dribbles": ("left", 640),
    "tackles_won/tackles_lost": ("right", 358),
    "fouls": ("right", 384),
    "penalties_conceded": ("right", 409),
    "interceptions/blocks": ("right", 460),
    "out_of_position": ("right", 486),
    "possession_won/possession_lost": ("right", 537),
    "clearances": ("right", 563),
    "headers_won/headers_lost": ("right", 588),
    "shot_accuracy_pct": ("left", 333),
    "pass_accuracy_pct": ("left", 409),
    "tackle_accuracy_pct": ("right", 333),
}
GOALKEEPER_ROWS = {
    "goals_conceded": ("left", 333),
    "shots_caught/shots_parried": ("left", 358),
    "crosses_caught": ("left", 384),
    "balls_stripped": ("left", 409),
    "assists": ("right", 324),
    "passes_completed_short/passes_completed_medium/passes_completed_long": (
        "right",
        350,
    ),
    "passes_failed_short/passes_failed_medium/passes_failed_long": ("right", 375),
    "key_passes": ("right", 401),
    "crosses_successful/crosses_failed": ("right", 427),
    "interceptions/blocks": ("right", 478),
    "out_of_position": ("right", 503),
    "possession_won/possession_lost": ("right", 555),
    "clearances": ("right", 580),
    "headers_won/headers_lost": ("right", 606),
    "pass_accuracy_pct": ("right", 299),
}


def compact(text):
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def classify(text):
    normalized = compact(text)
    if "playerperformance" in normalized:
        return (
            "goalkeeper_performance"
            if "goalkeeping" in normalized
            else "player_performance"
        )
    for marker, screen_type in (
        ("matchfacts", "match_facts"),
        ("careersquadhub", "squad"),
        ("careertransferhub", "transfer"),
        ("centralnews", "news"),
        ("officeinbox", "inbox"),
    ):
        if marker in normalized:
            return screen_type
    if (
        "playerstats" in normalized
        and "rank" in normalized
        and ("topscorers" in normalized or "assists" in normalized)
    ):
        return "player_leaderboard"
    if "congratulations" in normalized and "winner" in normalized:
        return "competition_result"
    if "winner" in normalized and (
        "semifinals" in normalized
        or "quarterfinals" in normalized
        or ("round1" in normalized and "round2" in normalized)
    ):
        return "knockout_bracket"
    if "scoresfixtures" in normalized and (
        "changecompetition" in normalized or "pickcompetition" in normalized
    ):
        return "league_table"
    if "standings" in normalized:
        return classify_dashboard(normalized)
    return "unknown"


def classify_dashboard(normalized):
    award = (
        re.search(
            r"(?:grabs|wins)(?:"
            + "|".join(month.lower() for month in MONTHS)
            + r")playerofthemonth",
            normalized,
        )
        or "playeroftheyear" in normalized
        or re.search(r"crowned.+champions?", normalized)
    )
    return "dashboard_award" if award else "dashboard"


def ordinal(number):
    if 10 <= number % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def parse_integer(text):
    text = text.strip()
    return int(text) if re.fullmatch(r"\d+", text) else None


def parse_number(text):
    text = text.strip().removesuffix("%")
    return float(text) if re.fullmatch(r"\d+(?:\.\d+)?", text) else None


def parse_counts(text, count, signed=False):
    parts = text.replace(" ", "").replace("−", "-").split("/")
    if len(parts) != count:
        return [None] * count
    if signed:
        return [int(part) if re.fullmatch(r"-?\d+", part) else None for part in parts]
    return [parse_integer(part) for part in parts]


def parse_money(text):
    matched = re.fullmatch(
        r"\s*(USD|GBP|EUR|CAD|AUD|INR|Rs|\$|\u00a3|\u20ac|\u20b9)?\s*"
        r"((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?)\s*([KM])?\s*",
        text,
        re.IGNORECASE,
    )
    if not matched:
        return None, None, None
    symbol, number, suffix = matched.groups()
    multiplier = {"K": 1000, "M": 1000000}.get((suffix or "").upper(), 1)
    amount = int(Decimal(number.replace(",", "")) * multiplier * 100)
    currency = {"\u00a3": "GBP", "\u20ac": "EUR", "\u20b9": "INR", "RS": "INR"}.get(
        (symbol or "").upper(),
        symbol.upper() if symbol and symbol != "$" else None,
    )
    return amount, currency, symbol


def parse_months(text):
    matched = re.fullmatch(
        r"\s*(\d+)\s*-?\s*(year|month)s?(?:\s*[\[(]s[\])])?\s*", text, re.IGNORECASE
    )
    if not matched or int(matched.group(1)) == 0:
        return None
    return int(matched.group(1)) * (12 if matched.group(2).lower() == "year" else 1)


def detected_fields(tokens, regions, single_line=False):
    fields = {}
    for field, bounds in regions.items():
        normalized = [
            bounds[0] / BASE_WIDTH,
            bounds[1] / BASE_HEIGHT,
            bounds[2] / BASE_WIDTH,
            bounds[3] / BASE_HEIGHT,
        ]
        selected = [
            token
            for token in tokens
            if normalized[0]
            <= sum(point[0] for point in token["box"]) / len(token["box"])
            <= normalized[2]
            and normalized[1]
            <= sum(point[1] for point in token["box"]) / len(token["box"])
            <= normalized[3]
        ]
        selected.sort(
            key=lambda token: (
                0 if single_line else min(point[1] for point in token["box"]),
                min(point[0] for point in token["box"]),
            )
        )
        fields[field] = {
            "box": normalized,
            "method": "rapidocr_detected_region",
            "raw_text": " ".join(token["text"].strip() for token in selected),
            "confidence": min((token["confidence"] for token in selected), default=0.0),
        }
    return fields


def parse_header(text):
    cleaned = re.sub(r"0October|0ctober", "October", text, flags=re.IGNORECASE)
    pattern = r"(\d{1,2})\s*(" + "|".join(MONTHS) + r")\s*(20\d{2})"
    matched = re.search(pattern, cleaned, re.IGNORECASE)
    played_on = season = None
    if matched:
        month = next(
            index + 1
            for index, name in enumerate(MONTHS)
            if name.casefold() == matched.group(2).casefold()
        )
        try:
            played_on = date(
                int(matched.group(3)), month, int(matched.group(1))
            ).isoformat()
        except ValueError:
            played_on = None
        if played_on:
            season_year = int(matched.group(3)) - (month < 7)
            season = f"{season_year}/{str(season_year + 1)[-2:]}"
    competition = next(
        (
            name
            for alias, name in COMPETITION_LABELS.items()
            if alias in compact(cleaned).replace("0", "o")
        ),
        None,
    )
    sections = re.split(r"\s*[|/]\s*|\s+[Il]\s+", cleaned)
    venue = sections[1].strip() if len(sections) >= 3 else None
    if venue is None and matched:
        remainder = cleaned[matched.end() :].strip()
        sections = re.split(r"\s*[|/]\s*|\s+[Il]\s+", remainder)
        if len(sections) == 2 and any(
            alias in compact(sections[1]) for alias in COMPETITION_LABELS
        ):
            venue = sections[0].strip()
    return {
        "played_on": played_on,
        "season": season,
        "competition": competition,
        "venue": canonical_venue_name(venue) if venue else None,
    }


def parse_profile_details(text):
    matched = re.search(
        rf"(?<![A-Za-z])({POSITIONS}(?:\s*/\s*{POSITIONS})*)\s*[|Il]?\s*"
        r"Age\s*:?\s*(\d{1,2})(?!\d)(.*)$",
        text.strip(),
        re.IGNORECASE,
    )
    if not matched:
        return {}
    details = {
        "displayed_position": re.sub(r"\s+", "", matched.group(1)).upper(),
        "age": int(matched.group(2)),
    }
    if country := normalize_nationality(matched.group(3)):
        details["nationality"] = country
    return details


def club_name(text):
    if not text.strip():
        return None
    text = canonical_club_name(text)
    words = text.strip().title().split()
    return (
        " ".join(
            word.upper()
            if word.upper()
            in {"FC", "MK", "AFC", "QPR", "SK", "AJ", "CP", "RSC", "CF", "SCO"}
            else word
            for word in words
        )
        or None
    )


def news_title(text):
    return re.sub(r"^(?:[O0]\s+|O(?=[A-Z]))", "", text.strip())


def parse_news_date(text):
    matched = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})/(20\d{2})\s*", text)
    if matched:
        try:
            return date(
                int(matched.group(3)), int(matched.group(2)), int(matched.group(1))
            ).isoformat()
        except ValueError:
            pass
    return None


def parse_calendar_month(text):
    labels = "|".join((*MONTHS, *(month[:3] for month in MONTHS)))
    matched = re.search(
        r"(?<![a-z])(" + labels + r")\s*(?:(\d{1,2})\s*,\s*)?(20\d{2})\b",
        text,
        re.IGNORECASE,
    )
    if matched:
        month = next(
            index + 1
            for index, name in enumerate(MONTHS)
            if name[:3].casefold() == matched.group(1)[:3].casefold()
        )
        try:
            return date(
                int(matched.group(3)), month, int(matched.group(2) or 1)
            ).strftime("%Y-%m")
        except ValueError:
            pass
    return None


def clean_news_text(text):
    """Drop sponsor footers and repair only unambiguous vocabulary joins."""
    tail = re.search(
        r"(?:^|\s)(?:(?:[A-Z]{0,3}FIF[AR]\s*19|PA|RA|GA|EA|EFL|LEASUETW|A)\s*)+$",
        text,
    )
    if tail and len(re.findall(r"FIF[AR]\s*19", tail.group())) >= 2:
        text = text[: tail.start()].rstrip()
    return split_joined_words(text)


def parse_news_event(
    title, body="", announced_on=None, observed_on=None, *, sidebar=False
):
    title = split_joined_words(news_title(title))
    # Raw body text and token boxes remain untouched in the OCR evidence.
    body = clean_news_text(body)
    normalized = compact(title)
    if any(
        word in normalized
        for word in (
            "shortlist",
            "nominee",
            "nominated",
            "nomination",
            "expected",
            "likely",
            "prediction",
        )
    ):
        return None
    player = club = period = event_type = None
    competition = parse_header(f"{title} {body}")["competition"]
    event_date = (
        date.fromisoformat(announced_on or observed_on)
        if announced_on or observed_on
        else None
    )
    monthly = re.match(
        r"(.+?)\s*(?:grabs|wins)\s*("
        + "|".join(MONTHS)
        + r")\s*Player\s*of\s*the\s*Month",
        title,
        re.IGNORECASE,
    )
    champion = re.fullmatch(
        r"(.+?)\s*Crowned\s*(.+?)\s*Champions?[.!]?", title, re.IGNORECASE
    )
    cup_winner = re.fullmatch(
        r"(.+?)\s+(?:Win(?:s)?\s+(?:the\s+)?|emerge\s+as\s+|are\s+)(.+?)"
        r"(?:\s+winners)?[.!]?",
        title,
        re.IGNORECASE,
    )
    promotion = re.fullmatch(r"(.+?)\s+Secure\s+Promotion[.!]?", title, re.IGNORECASE)
    promoted_to = re.fullmatch(
        r"(.+?)\s+Promoted\s+to\s+(?:the\s+)?(.+?)[.!]?", title, re.IGNORECASE
    )
    golden_boot = re.fullmatch(
        r"(.+?)\s*Wins\s*Golden\s*Boot[.!]?", title, re.IGNORECASE
    )
    golden_boot_for = re.fullmatch(
        r"Golden\s*Boot\s+for\s+(?:Marksman|Sharpshooter|Top\s*Scorer)\s+(.+?)[.!]?",
        title,
        re.IGNORECASE,
    )
    review = re.fullmatch(
        r"(.+?)\s+Review\s*:\s*(.+?)\s+(?:vs\.?|v\.?)\s+(.+?)[.!]?",
        title,
        re.IGNORECASE,
    )
    award = re.fullmatch(
        r"(player|goalkeeper)ofthe(competition|tournament)(?:announced)?", normalized
    )
    annual = re.fullmatch(
        r"Player\s*of\s*the\s*Year\s*Announced(?:\s*[:\-]?\s*(.+?))?[.!]?",
        title,
        re.IGNORECASE,
    )
    annual_winner = re.fullmatch(
        r"(.+?)\s*(?:wins|named)\s*(?:the\s*)?(?:(20\d{2})\s*)?"
        r"Player\s*of\s*the\s*Year(?:\s*Award)?[.!]?",
        title,
        re.IGNORECASE,
    )
    if monthly:
        event_type = "player_of_the_month"
        player = monthly.group(1).strip()
        month = next(
            index + 1
            for index, name in enumerate(MONTHS)
            if name.casefold() == monthly.group(2).casefold()
        )
        period = MONTHS[month - 1]
        if event_date:
            event_date = date(event_date.year - (month > event_date.month), month, 1)
            period = event_date.strftime("%Y-%m")
        employer = re.search(r"performance\s*for\s*(.+?)\s*earned", body, re.IGNORECASE)
        if employer:
            club = club_name(employer.group(1))
    elif annual or annual_winner:
        player = annual.group(1) if annual else annual_winner.group(1)
        if not player:
            named = re.match(
                r"(?:(.+?)['\u2019]s\s+)?(.+?)\s+has\s+been\s+named\s+"
                r"(?:the\s+)?Player\s+of\s+the\s+Year\b",
                body,
                re.IGNORECASE,
            )
            player = named.group(2) if named else None
            club = club_name(named.group(1)) if named and named.group(1) else None
        if not player or not player.strip(" .!:-"):
            return None
        player = player.strip(" .!:-")
        event_type = "player_of_the_year"
        competition = None
        explicit_year = annual_winner.group(2) if annual_winner else None
        period = explicit_year or (str(event_date.year) if event_date else None)
    elif champion:
        event_type = "champion"
        club = club_name(champion.group(1))
        competition = parse_header(champion.group(2))["competition"]
    elif cup_winner and parse_header(cup_winner.group(2))["competition"]:
        event_type = "champion"
        club = club_name(cup_winner.group(1))
        competition = parse_header(cup_winner.group(2))["competition"]
    elif promotion and re.search(r"\bclinched\s+promotion\s+to\b", body, re.IGNORECASE):
        event_type = "promotion"
        club = club_name(promotion.group(1))
        destination = re.search(
            r"promotion\s+to\s+(?:the\s+)?(.+?)(?:\s+in\b|[.!])", body, re.IGNORECASE
        )
        competition = (
            parse_header(destination.group(1))["competition"] if destination else None
        )
    elif promoted_to and re.search(r"promot", body, re.IGNORECASE):
        event_type = "promotion"
        club = club_name(promoted_to.group(1))
        competition = parse_header(promoted_to.group(2))["competition"]
    elif golden_boot or golden_boot_for:
        # A neighboring headline is not evidence that its winner belongs in the
        # managed squad. Keep selected articles and global annual awards intact.
        if sidebar:
            return None
        event_type = "golden_boot"
        player = (golden_boot or golden_boot_for).group(1).strip()
    elif award:
        event_type = f"{award.group(1)}_of_the_competition"
        ownership = re.match(
            r"(.+?)['\u2019]s\s*(.+?)\s*has\s*been\s*named", body, re.IGNORECASE
        )
        named = re.match(r"(.+?)\s*has\s*been\s*named", body, re.IGNORECASE)
        if ownership:
            club = club_name(ownership.group(1))
            player = ownership.group(2).strip()
        elif named:
            player = named.group(1).strip()
            employer = re.search(r"\bThe\s+([^.!?]+?)\s+stopper\b", body, re.IGNORECASE)
            if employer:
                club = club_name(employer.group(1))
        else:
            announced = re.search(
                r"(?:announced|anounced)\s+as\s+being\s+(.+?)['\u2019]s\s+(.+?)[.!]?$",
                body,
                re.IGNORECASE,
            )
            if not announced:
                return None
            club = club_name(announced.group(1))
            player = announced.group(2).strip()
    elif review:
        competition = parse_header(review.group(1))["competition"]
        finalists = {
            club_name(review.group(2)) or "",
            club_name(review.group(3)) or "",
        } - {""}
        winner = next(
            (
                name
                for name in finalists
                if re.search(
                    rf"\b{re.escape(name)}\s+who\s+"
                    r"(?:were|was|have\s+been)\s+promoted\b",
                    body,
                    re.IGNORECASE,
                )
            ),
            None,
        )
        if not winner or not competition:
            return None
        event_type = "champion"
        club = winner
    else:
        return None
    season_year = event_date.year - (event_date.month < 7) if event_date else None
    season = f"{season_year}/{str(season_year + 1)[-2:]}" if season_year else None
    if event_type == "player_of_the_year":
        season = None
    return {
        "type": "competition_event",
        "event_type": event_type,
        "player": player,
        "club": club,
        "competition": competition,
        "season": season,
        "announced_on": announced_on,
        "period": period or season,
        "description": f"{title}. {body}".strip(),
    }


def repeated_number(reading, max_digits=1):
    text, copies = reading["raw_text"], reading["copies"]
    width = len(text) // copies
    if (
        reading["confidence"] >= 0.6
        and re.fullmatch(r"[0-9]+", text)
        and 1 <= width <= max_digits
        and text == text[:width] * copies
    ):
        return text[:width]
    return None


class ScreenshotExtractor:
    def __init__(self, engine=None):
        if engine is None:
            from rapidocr_onnxruntime import RapidOCR

            engine = RapidOCR()
        self.engine = engine

    def recognize(self, image, regions, integer_fields=(), verify_numeric=False):
        crops = []
        evidence = {}
        for field, bounds in regions.items():
            normalized = [
                bounds[0] / BASE_WIDTH,
                bounds[1] / BASE_HEIGHT,
                bounds[2] / BASE_WIDTH,
                bounds[3] / BASE_HEIGHT,
            ]
            actual = (
                round(normalized[0] * image.width),
                round(normalized[1] * image.height),
                round(normalized[2] * image.width),
                round(normalized[3] * image.height),
            )
            crops.append(np.asarray(image.crop(actual))[:, :, ::-1].copy())
            evidence[field] = {"box": normalized, "method": "rapidocr_recognizer_crop"}
        readings, elapsed = self.engine.text_recognizer(crops)
        if len(readings) != len(regions):
            raise ValueError(
                "OCR returned a different number of readings than supplied regions"
            )
        for field, (text, confidence) in zip(regions, readings):
            evidence[field].update(raw_text=text, confidence=float(confidence))
        retries = []
        retry_fields = []
        for field, crop in zip(regions, crops):
            if field not in integer_fields or (
                parse_integer(evidence[field]["raw_text"]) is not None
                and (not verify_numeric or evidence[field]["confidence"] >= 0.85)
            ):
                continue
            grayscale = Image.fromarray(crop[:, :, ::-1]).convert("L")
            if np.median(np.asarray(grayscale)) < 128:
                grayscale = ImageOps.invert(grayscale)
            binary = grayscale.point(lambda value: 0 if value < 160 else 255)
            bounds = ImageOps.invert(binary).getbbox()
            if bounds is None or bounds[3] - bounds[1] < max(3, binary.height * 0.35):
                continue
            glyph = ImageOps.autocontrast(grayscale.crop(bounds))
            glyph = glyph.resize(
                (max(1, round(glyph.width * 48 / glyph.height)), 48),
                Image.Resampling.LANCZOS,
            )
            variants = {"grayscale": glyph}
            if verify_numeric:
                variants["threshold"] = glyph.point(
                    lambda value: 0 if value < 160 else 255
                )
                variants["wide"] = glyph.resize(
                    (round(glyph.width * 1.5), 48), Image.Resampling.LANCZOS
                )
            for variant, glyph_image in variants.items():
                for copies in (3, 5):
                    strip = Image.new(
                        "L", ((glyph_image.width + 8) * copies + 8, 64), 255
                    )
                    for index in range(copies):
                        strip.paste(
                            glyph_image, (8 + index * (glyph_image.width + 8), 8)
                        )
                    retries.append(np.asarray(strip.convert("RGB"))[:, :, ::-1].copy())
                    retry_fields.append((field, copies, variant))
        if retries:
            recovered, elapsed = self.engine.text_recognizer(retries)
            if len(recovered) != len(retry_fields):
                raise ValueError(
                    "OCR returned a different number of numeric retry readings than supplied regions"
                )
            for (field, copies, variant), (text, confidence) in zip(
                retry_fields, recovered
            ):
                evidence[field].setdefault("numeric_retry", []).append(
                    {
                        "copies": copies,
                        "variant": variant,
                        "raw_text": text,
                        "confidence": float(confidence),
                    }
                )
            for field in dict.fromkeys(
                field for field, copies, variant in retry_fields
            ):
                readings = evidence[field]["numeric_retry"]
                valid = [
                    (reading, repeated_number(reading, 3 if verify_numeric else 1))
                    for reading in readings
                ]
                valid = [
                    (reading, value) for reading, value in valid if value is not None
                ]
                values = {value for reading, value in valid}
                copies = {reading["copies"] for reading, value in valid}
                confidence = min(
                    (reading["confidence"] for reading, value in valid), default=0
                )
                original_value = parse_integer(evidence[field]["raw_text"])
                if (
                    len(values) == 1
                    and copies == {3, 5}
                    and (
                        original_value is None
                        or int(next(iter(values))) == original_value
                        or confidence > evidence[field]["confidence"] + 0.05
                    )
                ):
                    evidence[field]["initial_reading"] = {
                        "raw_text": evidence[field]["raw_text"],
                        "confidence": evidence[field]["confidence"],
                    }
                    evidence[field].update(
                        raw_text=next(iter(values)),
                        confidence=confidence,
                        method="rapidocr_repeated_number_crop"
                        if verify_numeric
                        else "rapidocr_repeated_digit_crop",
                    )
        return evidence

    def refine_name_fields(
        self, image, tokens, fields, name_fields=("first_name", "last_name")
    ):
        for field in name_fields:
            original = fields[field]
            left, top, right, bottom = original["box"]
            selected = [
                token
                for token in tokens
                if left <= sum(point[0] for point in token["box"]) / 4 <= right
                and top <= sum(point[1] for point in token["box"]) / 4 <= bottom
            ]
            if field in {"home_club", "away_club"}:
                selected = [
                    token
                    for token in selected
                    if all(
                        left - 3 / BASE_WIDTH <= x <= right + 3 / BASE_WIDTH
                        and top - 3 / BASE_HEIGHT <= y <= bottom + 3 / BASE_HEIGHT
                        for x, y in token["box"]
                    )
                ]
            selected.sort(key=lambda token: min(point[0] for point in token["box"]))
            detected = " ".join(token["text"].strip() for token in selected)
            if (
                not detected
                or compact(detected) == compact(original["raw_text"])
                or min(token["confidence"] for token in selected) < 0.7
            ):
                continue
            points = [point for token in selected for point in token["box"]]
            bounds = (
                min(point[0] for point in points) * BASE_WIDTH,
                min(point[1] for point in points) * BASE_HEIGHT,
                max(point[0] for point in points) * BASE_WIDTH,
                max(point[1] for point in points) * BASE_HEIGHT,
            )
            regions = {
                f"{field}.{padding}": (
                    max(0, bounds[0] - padding),
                    max(0, bounds[1] - padding),
                    min(BASE_WIDTH, bounds[2] + padding),
                    min(BASE_HEIGHT, bounds[3] + padding),
                )
                for padding in (0, 2, 4)
            }
            retries = self.recognize(image, regions)
            agreeing = [
                reading
                for reading in retries.values()
                if reading["confidence"] >= max(0.75, original["confidence"] + 0.015)
                and compact(reading["raw_text"]) == compact(detected)
            ]
            if len(agreeing) < 2 and field in {"first_name", "last_name"}:
                enlarged = self.recognize(
                    image.resize(
                        (image.width * 2, image.height * 2),
                        Image.Resampling.LANCZOS,
                    ),
                    regions,
                )
                retries = {
                    **retries,
                    **{f"{key}.enlarged": value for key, value in enlarged.items()},
                }
                agreeing = [
                    reading
                    for reading in enlarged.values()
                    if reading["confidence"]
                    >= max(0.75, original["confidence"] + 0.015)
                    and compact(reading["raw_text"]) == compact(detected)
                ]
            if len(agreeing) >= 2:
                retry = max(agreeing, key=lambda reading: reading["confidence"])
                fields[field] = {
                    **retry,
                    "initial_reading": original,
                    "full_image_reading": detected,
                    "name_retry": list(retries.values()),
                    "method": "rapidocr_detected_name_consensus",
                }

    def extract(self, path):
        with Image.open(path) as original:
            image = original.convert("RGB")
        detections, elapsed = self.engine(np.asarray(image)[:, :, ::-1].copy())
        detections = detections or []
        tokens = [
            {
                "text": text,
                "confidence": float(confidence),
                "box": [
                    [float(point[0]) / image.width, float(point[1]) / image.height]
                    for point in polygon
                ],
            }
            for polygon, text, confidence in detections
        ]
        screen_type = classify("\n".join(token["text"] for token in tokens))
        evidence = {
            "full_image_tokens": tokens,
            "extractor_version": EXTRACTOR_VERSION,
            "dimensions": [image.width, image.height],
            "fields": {},
        }
        issues = []
        if abs(image.width / image.height - BASE_WIDTH / BASE_HEIGHT) > 0.015:
            return {
                "screen_type": screen_type,
                "records": [],
                "evidence": evidence,
                "issues": [
                    "Unsupported aspect ratio; inspect the screenshot and establish its layout."
                ],
            }
        if screen_type == "match_facts":
            record, fields = self.extract_match(image)
            records = [record]
        elif screen_type in {"player_performance", "goalkeeper_performance"}:
            record, fields = self.extract_player(
                image, screen_type == "goalkeeper_performance"
            )
            records = [record]
            issues.append(
                "Match linking requires a valid preceding match summary with uninterrupted player screenshots."
            )
        elif screen_type == "squad":
            record, fields = self.extract_snapshot(image)
            records = [record]
            issues.append(
                "Only the selected player's profile and visible competition totals are extracted."
            )
            issues.append(
                "The season requires related dated fixture or competition-table evidence; an exact observation date is not visible."
            )
            squad_text = compact(" ".join(token["text"] for token in tokens)).replace(
                "0", "o"
            )
            if "totals" in squad_text and any(
                alias in squad_text for alias in COMPETITION_LABELS
            ):
                additional_records, totals_fields, totals_issues = (
                    self.extract_squad_totals(image, record)
                )
                records.extend(additional_records)
                fields.update(totals_fields)
                issues.extend(totals_issues)
                issues.append(
                    "Cumulative totals are separate observations, not extra match statistics."
                )
            roster, roster_fields = self.extract_squad_roster(image, tokens, record)
            if roster:
                records.extend(roster)
                fields.update(roster_fields)
                issues.append(
                    "Jersey numbers come from the visible STATUS roster list; rows without a readable number are not imported."
                )
        elif screen_type == "transfer":
            records, fields, transfer_issues = self.extract_transfer(tokens)
            issues.extend(transfer_issues)
        elif screen_type == "news":
            records, fields, news_issues = self.extract_news(tokens)
            issues.extend(news_issues)
        elif screen_type == "inbox":
            records, fields, inbox_issues = self.extract_inbox(tokens)
            issues.extend(inbox_issues)
        elif screen_type == "player_leaderboard":
            records, fields, leaderboard_issues = self.extract_leaderboard(
                image, tokens
            )
            issues.extend(leaderboard_issues)
        elif screen_type == "dashboard_award":
            records, fields, news_issues = self.extract_dashboard_award(image, tokens)
            issues.extend(news_issues)
        elif screen_type == "competition_result":
            records, fields = self.extract_competition_result(tokens)
            issues.append(
                "The winner screen does not show its season or exact announcement date."
            )
        elif screen_type == "knockout_bracket":
            records, fields = self.extract_knockout_bracket(tokens)
            issues.append(
                "The bracket screen does not show its season or exact announcement date."
            )
        elif screen_type == "league_table":
            records, fields, table_issues = self.extract_league_table(image, tokens)
            issues.extend(table_issues)
        else:
            return {
                "screen_type": screen_type,
                "records": [],
                "evidence": evidence,
                "issues": [
                    f"{screen_type}: no supported statistics detected; OCR evidence is retained."
                ],
            }
        if screen_type == "match_facts":
            self.refine_name_fields(image, tokens, fields, ("home_club", "away_club"))
            for side in ("home", "away"):
                records[0][f"{side}_club"] = club_name(
                    fields[f"{side}_club"]["raw_text"]
                )
        if screen_type in {"squad", "player_performance", "goalkeeper_performance"}:
            self.refine_name_fields(image, tokens, fields)
            name = " ".join(
                fields[field]["raw_text"].strip()
                for field in ("first_name", "last_name")
            )
            for record in records:
                if record.get("type") != "player_jersey":
                    record["player"] = name
        for record in records:
            if not record.get("player"):
                continue
            country, basis = resolve_nationality(
                record["player"], record.get("nationality")
            )
            if country:
                record["nationality"] = country
            if basis:
                record["nationality_basis"] = basis
                evidence.setdefault("nationality_fallbacks", []).append(
                    {"player": record["player"], "nationality": country, **basis}
                )
                issues.append(
                    f"Nationality for {record['player']} supplied by {basis['method']}; not an on-screen OCR reading."
                )
        evidence["fields"] = fields
        issues.extend(
            f"Negative count displayed for {field}: {reading['raw_text']!r}; retained as OCR evidence, not replaced with zero."
            for field, reading in fields.items()
            if "/" in field
            and re.search(r"(?:^|/)\s*[-−]\d", reading["raw_text"])
            and not reading.get("normalization")
        )
        issues.extend(
            f"User-confirmed absolute-count rule for {field}: {reading['raw_text']!r} -> {reading['normalization']['stored_values']}; displayed percentage retained."
            for field, reading in fields.items()
            if reading.get("normalization")
        )
        issues.extend(
            f"Low OCR confidence for {field}: {reading['confidence']:.2f}"
            for field, reading in fields.items()
            if reading["confidence"] < 0.85
        )
        return {
            "screen_type": screen_type,
            "records": records,
            "evidence": evidence,
            "issues": issues,
        }

    def extract_transfer(self, tokens):
        fields = detected_fields(
            tokens,
            {
                "panel_heading": (684, 195, 1040, 225),
                "player": (697, 228, 986, 287),
                "to_club": (733, 287, 982, 309),
                "weekly_wage_minor": (692, 357, 806, 383),
                "contract_months": (813, 357, 928, 383),
                "loan_months": (733, 508, 829, 565),
                "transfer_type": (953, 508, 1053, 565),
                "completion": (685, 385, 1054, 453),
                "status": (865, 510, 947, 565),
            },
        )
        fields.update(
            detected_fields(
                tokens,
                {"profile_details": (697, 310, 1120, 339)},
                single_line=True,
            )
        )
        text = {field: reading["raw_text"] for field, reading in fields.items()}
        completed = "andhejustjoinedtheteam" in compact(text["completion"])
        precontract = "agreedprecontractterms" in compact(text["completion"])
        transfer_type = {"transfer": "permanent", "loan": "loan"}.get(
            compact(text["transfer_type"])
        )
        panel = compact(text["panel_heading"])
        if (
            panel not in {"contractoffers", "transferoffers"}
            or compact(text["status"]) != "accepted"
            or not transfer_type
            or not text["player"]
            or not text["to_club"]
        ):
            return (
                [],
                fields,
                [
                    "No accepted signing or agreed pre-contract in the selected contract panel."
                ],
            )
        if panel == "transferoffers":
            # Transfer-offer panels show player value, wage and release clause
            # where contract panels show wage, contract length and squad role.
            fields.update(
                detected_fields(
                    tokens,
                    {
                        "weekly_wage_minor": (808, 352, 898, 382),
                        "transfer_fee_minor": (720, 505, 830, 560),
                    },
                )
            )
            text = {field: reading["raw_text"] for field, reading in fields.items()}
        date_text = ""
        surname = compact(text["player"].split()[-1])
        selected_rows = [
            token
            for token in tokens
            if 320 / BASE_WIDTH
            < min(point[0] for point in token["box"])
            < 520 / BASE_WIDTH
            and 255 / BASE_HEIGHT
            < min(point[1] for point in token["box"])
            < 645 / BASE_HEIGHT
            and compact(token["text"]).endswith(surname)
        ]
        if len(selected_rows) == 1:
            center = (
                sum(point[1] for point in selected_rows[0]["box"])
                / len(selected_rows[0]["box"])
                * BASE_HEIGHT
            )
            fields.update(
                detected_fields(
                    tokens, {"effective_on": (580, center - 14, 667, center + 14)}
                )
            )
            date_text = fields["effective_on"]["raw_text"]
        wage, currency, symbol = parse_money(text["weekly_wage_minor"])
        fee = None
        if panel == "transferoffers" and transfer_type == "permanent":
            fee, fee_currency, fee_symbol = parse_money(text["transfer_fee_minor"])
            currency = currency or fee_currency
            symbol = symbol or fee_symbol
        record = {
            "type": "player_transfer",
            "player": text["player"],
            "from_club": None,
            "to_club": club_name(text["to_club"]),
            "transfer_type": transfer_type,
            "effective_on": None,
            "date_basis": f"{date_text or 'No exact date'} shown in the selected transfer row; year requires review.",
            "fee_minor": fee,
            "weekly_wage_minor": wage,
            "currency": currency,
            "currency_display": symbol,
            "contract_months": parse_months(text["contract_months"]),
            "loan_months": parse_months(text["loan_months"])
            if transfer_type == "loan"
            else None,
        }
        if country := parse_profile_details(text["profile_details"]).get("nationality"):
            record["nationality"] = country
        if not completed:
            record["context_basis"] = (
                "User-confirmed archive rule: accepted contract-panel transfers are completed "
                "even when the capture does not yet say the player joined. No exact completion date inferred."
            )
        if precontract:
            # An accepted pre-contract still displays the player's current club,
            # not the club to which the archive owner confirms the player moved.
            fields.update(detected_fields(tokens, {"career_club": (145, 84, 276, 114)}))
            career_club = fields["career_club"]["raw_text"].strip()
            record["from_club"] = record["to_club"]
            record["to_club"] = (
                club_name(career_club) if career_club else "Notts County"
            )
            record["context_basis"] = (
                "User-confirmed archive rule: accepted pre-contracts are completed transfers "
                "to the managed club. The selected panel shows the selling club; "
                "no exact completion date inferred."
            )
            fields["current_weekly_wage_minor"] = fields["weekly_wage_minor"]
            fields["weekly_wage_minor"] = {
                **fields["loan_months"],
                "method": "rapidocr_accepted_precontract_offer",
            }
            wage, currency, symbol = parse_money(text["loan_months"])
            record.update(
                weekly_wage_minor=wage, currency=currency, currency_display=symbol
            )
            # The expiry counter describes the old contract, not the new deal.
            record["contract_months"] = None
            record["date_basis"] += (
                " Pre-contract capture date, not a known completion date."
            )
        return (
            [record],
            fields,
            [
                record.get(
                    "context_basis",
                    "Confirm the transfer date/year and selling club; neither is inferred from a badge or filename.",
                ),
                "The Offer amount is the accepted transfer fee paid by the managed club."
                if fee is not None
                else "The contract offer is not a transfer fee. A dollar symbol alone does not identify its currency.",
            ],
        )

    def extract_news(self, tokens):
        # The body starts at y=274 for one-line titles and y=306 for
        # two-line titles. Use the second title line's top, not its centre,
        # to avoid folding "Announced" into a club or swallowing body text.
        wrapped_title = any(
            949 / BASE_WIDTH <= min(point[0] for point in token["box"])
            and 258 / BASE_HEIGHT
            <= min(point[1] for point in token["box"])
            < 269 / BASE_HEIGHT
            for token in tokens
        )
        title_bottom = 291 if wrapped_title else 268
        fields = detected_fields(
            tokens,
            {
                "article.title": (949, 225, 1267, title_bottom),
                "article.body": (949, title_bottom, 1267, 640),
            },
        )
        title = fields["article.title"]["raw_text"]
        body = fields["article.body"]["raw_text"]
        stories = []
        for row_index in range(6):
            top = 198 + row_index * 74.8
            prefix = f"news.{row_index}"
            fields.update(
                detected_fields(
                    tokens,
                    {
                        f"{prefix}.title": (79, top + 7, 369, top + 49),
                        f"{prefix}.announced_on": (99, top + 50, 230, top + 70),
                    },
                )
            )
            headline = fields[f"{prefix}.title"]["raw_text"]
            announced_on = parse_news_date(fields[f"{prefix}.announced_on"]["raw_text"])
            stories.append((headline, announced_on))
        matching = [
            announced_on
            for headline, announced_on in stories
            if compact(news_title(headline)) == compact(news_title(title))
        ]
        matching_dates = set(matching)
        selected = parse_news_event(
            title,
            body,
            next(iter(matching_dates)) if len(matching_dates) == 1 else None,
        )
        records = [selected] if selected else []
        transfer_interest = re.match(
            r"Assist Leader (.+?) Targeted by\b", news_title(title), re.IGNORECASE
        )
        if transfer_interest:
            player = transfer_interest.group(1).strip()
            current_club = re.search(
                r"\bin demand than (.+?)['\u2019]s\s+" + re.escape(player) + r"\b",
                body,
                re.IGNORECASE,
            )
            if current_club:
                records.append(
                    {
                        "type": "competition_event",
                        "event_type": "transfer_interest",
                        "player": player,
                        "club": club_name(current_club.group(1)),
                        "competition": None,
                        "season": None,
                        "announced_on": next(iter(matching_dates))
                        if len(matching_dates) == 1
                        else None,
                        "period": None,
                        "description": f"{clean_news_text(news_title(title))}. {clean_news_text(body)} [Transfer interest only; no completed move recorded.]",
                    }
                )
        for headline, announced_on in stories:
            if selected and compact(news_title(headline)) == compact(news_title(title)):
                continue
            record = parse_news_event(headline, announced_on=announced_on, sidebar=True)
            if record:
                records.append(record)
        issues = []
        if not records:
            issues.append(
                "No named award winner or championship found; predictions and shortlists are not awards."
            )
        for record in records:
            if record["type"] != "competition_event":
                continue
            if record["event_type"] == "player_of_the_year":
                if not record["period"]:
                    issues.append("The Player of the Year award year is not stated.")
            elif record["event_type"] != "transfer_interest" and (
                not record["competition"] or not record["season"]
            ):
                issues.append(
                    f"Competition or season is not stated in the award text: {record['description']}"
                )
            if record["player"]:
                issues.append(
                    f"Resolve {record['player']} against recorded player identities; news may display only a surname."
                )
        return records, fields, issues

    def extract_inbox(self, tokens):
        fields = detected_fields(
            tokens,
            {
                "effective_on": (790, 216, 960, 238),
                "sender": (795, 237, 1268, 255),
                "subject": (795, 289, 1268, 321),
                "body": (697, 338, 1270, 641),
                "club": (145, 84, 276, 114),
            },
        )
        body = fields["body"]["raw_text"]
        effective_on = parse_news_date(fields["effective_on"]["raw_text"])
        sender = fields["sender"]["raw_text"].strip()
        subject = compact(fields["subject"]["raw_text"])
        badge = fields["club"]["raw_text"].strip()
        club = (
            club_name(badge)
            if badge
            and not re.search(
                r"objectives|overview|rating|update", badge, re.IGNORECASE
            )
            else "Notts County"
        )
        club_basis = (
            "Managed club inferred as Notts County; the on-screen badge area did not show a club name."
            if club == "Notts County" and "nottscounty" not in compact(badge)
            else None
        )
        if (
            "contractaccepted" in subject
            and re.search(
                r"\baccept your contract offer with the senior team\b",
                body,
                re.IGNORECASE,
            )
            and effective_on
            and len(sender.split()) >= 2
            and club
        ):
            record = {
                "type": "player_transfer",
                "player": sender,
                "to_club": club,
                "transfer_type": "permanent",
                "effective_on": effective_on,
                "date_basis": "Dated player email confirms acceptance of a senior-team contract; financial terms and former club are not shown.",
            }
            if club_basis:
                record["context_basis"] = club_basis
            return [record], fields, []
        loan = re.search(
            r"(?:Mr\.\s*[^,]+,?\s*)?(.+?)\s+has\s+accepted\s+a\s+"
            r"(One|Two|\d+)[- ]year\s+loan\s+move\s+to\s+(.+?)\.",
            body,
            re.IGNORECASE,
        )
        if (
            loan
            and "loanedout" in subject
            and effective_on
            and "immediately" in body.casefold()
        ):
            years = {"one": 1, "two": 2}.get(loan.group(2).casefold())
            years = years or parse_integer(loan.group(2))
            record = {
                "type": "player_transfer",
                "player": loan.group(1).strip(),
                "from_club": club,
                "to_club": club_name(loan.group(3)),
                "transfer_type": "loan",
                "effective_on": effective_on,
                "loan_months": years * 12,
                "date_basis": "Dated loan-confirmation email states that the player moves immediately.",
            }
            if club_basis:
                record["context_basis"] = club_basis
            return [record], fields, []
        returned = re.search(
            r"loan\s+deal\s+for\s+(.+?)\s+from\s+(.+?)\s+has\s+expired\s+and\s+"
            r"(?:he|they|she)\s+has\s+returned\s+(?:back\s+)?to\s+us\b",
            body,
            re.IGNORECASE,
        )
        if returned and "returningfromloan" in subject and effective_on:
            record = {
                "type": "player_transfer",
                "player": returned.group(1).strip(),
                "from_club": club_name(returned.group(2)),
                "to_club": club,
                "transfer_type": "loan_return",
                "effective_on": effective_on,
                "date_basis": "Dated email confirms the player's loan expired and he returned to the managed club.",
            }
            if club_basis:
                record["context_basis"] = club_basis
            return [record], fields, []
        expired = re.search(
            r"(.+?)['\u2019]s\s+loan\s+deal\s+has\s+expired\s+and\s+"
            r"(?:he|they|she)\s+has\s+been\s+sent\s+back\s+to\s+(.+?)[.!]",
            body,
            re.IGNORECASE,
        )
        if expired and "loanhasexpired" in subject and effective_on:
            record = {
                "type": "player_transfer",
                "player": expired.group(1).split(",")[-1].strip(),
                "from_club": club,
                "to_club": club_name(expired.group(2)),
                "transfer_type": "loan_return",
                "effective_on": effective_on,
                "date_basis": "Dated email confirms the player's loan spell at the managed club expired; he returned to his parent club.",
            }
            if club_basis:
                record["context_basis"] = club_basis
            return [record], fields, []
        return (
            [],
            fields,
            [
                "No dated senior-contract acceptance, completed loan or loan return confirmed in the selected email."
            ],
        )

    def extract_leaderboard(self, image, tokens):
        fields = detected_fields(
            tokens,
            {
                "competition": (240, 117, 725, 154),
                "statistic": (240, 170, 550, 204),
            },
        )
        competition = parse_header(fields["competition"]["raw_text"])["competition"]
        statistic = {"topscorers": "goals", "assists": "assists"}.get(
            compact(fields["statistic"]["raw_text"])
        )
        if not competition or not statistic:
            return [], fields, ["Leaderboard competition or statistic is unreadable."]
        records = []
        for row_index in range(15):
            center = 262 + row_index * 25.6
            prefix = f"leaderboard.{row_index}"
            fields.update(
                detected_fields(
                    tokens,
                    {
                        f"{prefix}.player": (274, center - 12, 588, center + 12),
                        f"{prefix}.club": (633, center - 12, 973, center + 12),
                    },
                    single_line=True,
                )
            )
            club = fields[f"{prefix}.club"]["raw_text"]
            if compact(club) != "nottscounty":
                continue
            numeric = {
                f"{prefix}.{statistic}": (986, center - 11, 1025, center + 12),
                f"{prefix}.appearances": (1116, center - 11, 1155, center + 12),
            }
            fields.update(self.recognize(image, numeric, numeric, verify_numeric=True))
            records.append(
                {
                    "type": "player_competition_snapshot",
                    "player": fields[f"{prefix}.player"]["raw_text"].strip(),
                    "club": "Notts County",
                    "competition": competition,
                    "scope": "competition",
                    "season": None,
                    "observed_on": None,
                    "snapshot_kind": "in_season",
                    "date_basis": f"Visible {statistic} leaderboard; only appearances and {statistic} are shown. No exact cutoff date displayed.",
                    "appearances": parse_integer(
                        fields[f"{prefix}.appearances"]["raw_text"]
                    ),
                    statistic: parse_integer(
                        fields[f"{prefix}.{statistic}"]["raw_text"]
                    ),
                }
            )
        return (
            records,
            fields,
            [
                "Only visible Notts County leaderboard rows are recorded; other clubs remain in OCR evidence. Missing metrics are not zeroes."
            ],
        )

    def extract_competition_result(self, tokens):
        fields = detected_fields(
            tokens,
            {
                "competition": (139, 74, 654, 105),
                "club": (300, 509, 655, 550),
                "confirmation": (270, 211, 560, 310),
            },
        )
        confirmation = compact(fields["confirmation"]["raw_text"])
        competition = parse_header(fields["competition"]["raw_text"])["competition"]
        winner = club_name(fields["club"]["raw_text"])
        if (
            "winner" not in confirmation
            or "congratulations" not in confirmation
            or not winner
        ):
            return [], fields
        return [
            {
                "type": "competition_event",
                "event_type": "champion",
                "player": None,
                "club": winner,
                "competition": competition,
                "season": None,
                "announced_on": None,
                "period": None,
                "description": f"{winner} won {fields['competition']['raw_text']}.",
            }
        ], fields

    def extract_knockout_bracket(self, tokens):
        fields = detected_fields(
            tokens,
            {
                "competition": (105, 60, 420, 135),
                "winner": (240, 500, 700, 560),
                "finalist_one": (230, 560, 368, 600),
                "final_score": (368, 560, 450, 600),
                "finalist_two": (450, 560, 620, 600),
            },
        )
        competition = parse_header(fields["competition"]["raw_text"])["competition"]
        winner = club_name(fields["winner"]["raw_text"])
        if not winner or not competition:
            return [], fields
        description = f"{winner} won {competition}."
        finalists = (
            club_name(fields["finalist_one"]["raw_text"]),
            club_name(fields["finalist_two"]["raw_text"]),
        )
        score = re.fullmatch(
            r"\s*(\d+)\s*[-–—:]\s*(\d+)\s*",
            fields["final_score"]["raw_text"],
        )
        runner_up = next((club for club in finalists if club and club != winner), None)
        if runner_up and score and winner in finalists:
            goals = (
                (score.group(1), score.group(2))
                if winner == finalists[0]
                else (score.group(2), score.group(1))
            )
            description = (
                f"{winner} won {competition}, beating {runner_up} "
                f"{goals[0]}–{goals[1]} in the final."
            )
        return [
            {
                "type": "competition_event",
                "event_type": "champion",
                "player": None,
                "club": winner,
                "competition": competition,
                "season": None,
                "announced_on": None,
                "period": None,
                "description": description,
            }
        ], fields

    def extract_league_table(self, image, tokens):
        fields = detected_fields(
            tokens,
            {"competition_panel": (110, 70, 380, 120)},
        )
        competition = parse_header(fields["competition_panel"]["raw_text"])[
            "competition"
        ]
        row = next(
            (
                token
                for token in tokens
                if compact(token["text"]).replace("0", "o").startswith("notts")
            ),
            None,
        )
        if row is None or not competition:
            return (
                [],
                fields,
                [
                    "Notts County's row or the competition name is not visible on this table; "
                    "scroll to reveal both before capturing."
                ],
            )
        center = sum(point[1] for point in row["box"]) / len(row["box"]) * BASE_HEIGHT
        columns = {
            "position": (78, 108),
            "played": (490, 528),
            "won": (546, 584),
            "drawn": (603, 641),
            "lost": (659, 697),
            "goals_for": (716, 754),
            "goals_against": (773, 811),
            "points": (831, 869),
        }
        fields.update(
            self.recognize(
                image,
                {
                    field: (left, center - 16, right, center + 16)
                    for field, (left, right) in columns.items()
                },
                columns.keys(),
            )
        )
        values = {field: parse_integer(fields[field]["raw_text"]) for field in columns}
        if values["position"] is None or values["points"] is None:
            return (
                [],
                fields,
                ["The league table row for Notts County is not fully readable."],
            )
        description = (
            f"Notts County finished {ordinal(values['position'])} in {competition} "
            f"with {values['points']} points from {values['played']} games "
            f"(W{values['won']} D{values['drawn']} L{values['lost']}, "
            f"GF{values['goals_for']} GA{values['goals_against']})."
        )
        return (
            [
                {
                    "type": "competition_event",
                    "event_type": "league_table_position",
                    "player": None,
                    "club": "Notts County",
                    "competition": competition,
                    "season": None,
                    "announced_on": None,
                    "period": str(values["position"]),
                    "description": description,
                }
            ],
            fields,
            [
                "Final league position is read only from the visible standings row; "
                "the season is inferred from surrounding dated screenshots, not this screen."
            ],
        )

    def extract_dashboard_award(self, image, tokens):
        fields = detected_fields(
            tokens,
            {
                "calendar": (590, 208, 676, 236),
                "fixture_date": (87, 248, 373, 270),
                "headline.detected": (775, 438, 1136, 463),
                "headline.raised.detected": (700, 388, 1282, 420),
            },
            single_line=True,
        )
        enlarged = image.resize(
            (image.width * 2, image.height * 2), Image.Resampling.LANCZOS
        )
        fields.update(self.recognize(enlarged, {"headline": (779, 442, 1134, 459)}))
        months = {
            parse_calendar_month(fields[field]["raw_text"])
            for field in ("calendar", "fixture_date")
        }
        months.discard(None)
        observed_on = f"{next(iter(months))}-01" if len(months) == 1 else None
        record = parse_news_event(
            fields["headline"]["raw_text"], observed_on=observed_on
        )
        if record is None:
            record = parse_news_event(
                fields["headline.detected"]["raw_text"], observed_on=observed_on
            )
        if record is None:
            record = parse_news_event(
                fields["headline.raised.detected"]["raw_text"], observed_on=observed_on
            )
        if record is None:
            fields.update(
                self.recognize(enlarged, {"headline.raised": (700, 388, 1282, 420)})
            )
            record = parse_news_event(
                fields["headline.raised"]["raw_text"], observed_on=observed_on
            )
        if record and observed_on:
            record["context_basis"] = (
                f"Dashboard calendar {observed_on[:7]} supplies observation context; "
                "no exact announcement date inferred."
            )
        return (
            ([record] if record else []),
            fields,
            [
                "Dashboard month/year is observation context, not the award announcement date.",
                "Only the news headline identifies winners; upcoming fixtures, standings and the training player are not award evidence.",
            ],
        )

    def extract_match(self, image):
        regions = {
            "header": (250, 45, 1110, 72),
            "home_club": (250, 108, 584, 155),
            "away_club": (795, 108, 1136, 155),
            "home_goals": (597, 103, 644, 157),
            "away_goals": (725, 103, 774, 157),
            "clock": (619, 74, 753, 110),
        }
        for field, center in TEAM_ROWS.items():
            regions[f"home.{field}"] = (728, center - 10, 759, center + 10)
            regions[f"away.{field}"] = (1213, center - 10, 1239, center + 10)
        integer_fields = {
            f"{side}.{field}"
            for side in ("home", "away")
            for field in TEAM_ROWS
            if not field.endswith("_pct")
        }
        fields = self.recognize(image, regions, integer_fields)
        record = {"type": "match", **parse_header(fields["header"]["raw_text"])}
        for side in ("home", "away"):
            record[f"{side}_club"] = club_name(fields[f"{side}_club"]["raw_text"])
            record[f"{side}_goals"] = parse_integer(fields[f"{side}_goals"]["raw_text"])
        clock = re.sub(r"\s+", "", fields["clock"]["raw_text"]).upper()
        shootout = re.search(r"(\d+)\s*[-:]\s*(\d+).*PEN", clock, re.IGNORECASE)
        minutes = re.search(r"(?<!\d)(90|120)[:.]00(?!\d)", clock)
        record.update(
            home_penalties=int(shootout.group(1)) if shootout else None,
            away_penalties=int(shootout.group(2)) if shootout else None,
            duration_minutes=int(minutes.group(1))
            if minutes and not shootout
            else None,
            extra_time=True
            if "ET" in clock
            else (False if minutes and not shootout else None),
        )
        record["team_stats"] = {
            side: {
                field: (parse_number if field.endswith("_pct") else parse_integer)(
                    fields[f"{side}.{field}"]["raw_text"]
                )
                for field in TEAM_ROWS
            }
            for side in ("home", "away")
        }
        return record, fields

    def extract_player(self, image, goalkeeper=False):
        regions = {
            "first_name": (175, 139, 404, 163),
            "last_name": (175, 163, 404, 190),
            "overall": (174, 191, 224, 228),
            "displayed_position": (192, 253, 326, 280),
            "club": (544, 140, 726, 173),
            "rating": (746, 178, 853, 232),
        }
        rows = GOALKEEPER_ROWS if goalkeeper else OUTFIELD_ROWS
        for field, (side, center) in rows.items():
            right = 662 if side == "left" else 1193
            grouped = "/" in field or field.endswith("_pct")
            width = 100 if "/" in field else (66 if grouped else 26)
            regions[field] = (
                right - width,
                center - (11 if grouped else 10),
                right,
                center + (12 if grouped else 10),
            )
        integer_fields = {
            field for field in rows if "/" not in field and not field.endswith("_pct")
        }
        fields = self.recognize(image, regions, integer_fields | {"overall"})
        record = {
            "type": "player_match",
            "match_id": None,
            "player": " ".join(
                fields[field]["raw_text"].strip()
                for field in ("first_name", "last_name")
            ),
            "club": club_name(fields["club"]["raw_text"]),
            "overall": parse_integer(fields["overall"]["raw_text"]),
            "displayed_position": fields["displayed_position"]["raw_text"].strip()
            or None,
            "rating": parse_number(fields["rating"]["raw_text"]),
            "started": None,
            "minutes_played": None,
        }
        for field in rows:
            raw_text = fields[field]["raw_text"]
            parts = field.split("/")
            if len(parts) > 1:
                displayed = parse_counts(
                    raw_text, len(parts), signed=field == "tackles_won/tackles_lost"
                )
                stored = [
                    abs(value) if value is not None else None for value in displayed
                ]
                record.update(zip(parts, stored))
                if any(value is not None and value < 0 for value in displayed):
                    fields[field]["normalization"] = {
                        "rule": "absolute_displayed_count",
                        "displayed_values": displayed,
                        "stored_values": stored,
                        "basis": "User confirmed negative displayed tackle counts must use their absolute values.",
                    }
                    record["stat_adjustments"] = {
                        part: {
                            "rule": "absolute_displayed_count",
                            "displayed": value,
                            "stored": abs(value),
                        }
                        for part, value in zip(parts, displayed)
                        if value is not None and value < 0
                    }
            else:
                record[field] = (
                    parse_number if field.endswith("_pct") else parse_integer
                )(raw_text)
        return record, fields

    def extract_snapshot(self, image):
        regions = {
            "first_name": (698, 245, 962, 269),
            "last_name": (698, 270, 973, 302),
            "overall": (982, 268, 1028, 308),
            "displayed_position": (713, 310, 738, 335),
            "age": (764, 310, 784, 335),
            "nationality": (818, 310, 1039, 335),
            "profile_details": (697, 309, 1040, 336),
        }
        fields = self.recognize(image, regions, {"overall"}, verify_numeric=True)
        details = parse_profile_details(fields["profile_details"]["raw_text"])
        for field, value in details.items():
            fields[field] = {
                **fields["profile_details"],
                "raw_text": str(value),
                "initial_reading": fields[field],
                "method": "rapidocr_profile_details_line",
            }
        return {
            "type": "player_snapshot",
            "season": None,
            "club": "Notts County",
            "player": " ".join(
                fields[field]["raw_text"].strip()
                for field in ("first_name", "last_name")
            ),
            "overall": parse_integer(fields["overall"]["raw_text"]),
            "age": parse_integer(fields["age"]["raw_text"]),
            "displayed_position": normalize_positions(
                fields["displayed_position"]["raw_text"]
            ),
            "nationality": normalize_nationality(fields["nationality"]["raw_text"]),
            "snapshot_kind": "first_observed",
            "observed_on": None,
            "date_from": None,
            "date_to": None,
            "date_precision": "unknown",
            "date_basis": "No exact in-game date on this screen; the season requires related screenshot context.",
        }, fields

    def extract_squad_totals(self, image, profile=None):
        if profile is None:
            profile, profile_fields = self.extract_snapshot(image)
        regions = {}
        numeric_columns = {
            "appearances": (819, 843),
            "goals": (851, 875),
            "assists": (883, 907),
            "clean_sheets": (915, 939),
            "yellow_cards": (947, 971),
            "red_cards": (979, 1003),
            "average_rating": (1009, 1040),
        }
        for row_index, center in enumerate((410, 445, 479, 513, 547, 582)):
            prefix = f"season_totals.{row_index}"
            regions[f"{prefix}.competition"] = (701, center - 10, 809, center + 10)
            for field, (left, right) in numeric_columns.items():
                regions[f"{prefix}.{field}"] = (left, center - 10, right, center + 10)
        integer_fields = {
            field
            for field in regions
            if field.rsplit(".", 1)[-1] in numeric_columns
            and not field.endswith("average_rating")
        }
        evidence = self.recognize(image, regions, integer_fields, verify_numeric=True)
        records = []
        issues = []
        for row_index in range(6):
            prefix = f"season_totals.{row_index}"
            label = compact(evidence[f"{prefix}.competition"]["raw_text"]).replace(
                "0", "o"
            )
            if not label:
                continue
            total = label in {"total", "totals"}
            competition = next(
                (name for alias, name in COMPETITION_LABELS.items() if alias in label),
                None,
            )
            if not total and competition is None:
                issues.append(
                    "Season totals row label is not a recognized competition: "
                    f"{evidence[f'{prefix}.competition']['raw_text']!r}; its row was not imported."
                )
                continue
            record = {
                "type": "player_competition_snapshot",
                "player": profile["player"],
                "club": profile["club"],
                "season": None,
                "observed_on": None,
                "snapshot_kind": "in_season",
                "date_basis": "The season requires related career context; no exact observation cutoff is visible.",
                "scope": "all_competitions" if total else "competition",
            }
            if not total:
                record["competition"] = competition
            for field in numeric_columns:
                raw_text = evidence[f"{prefix}.{field}"]["raw_text"]
                record[field] = (
                    parse_number if field == "average_rating" else parse_integer
                )(raw_text)
            records.append(record)
        return records, evidence, issues

    def extract_squad_roster(self, image, tokens, profile):
        header = set()
        names = []
        for token in tokens:
            left = min(point[0] for point in token["box"])
            cy = sum(point[1] for point in token["box"]) / 4
            text = token["text"].strip()
            if 0.26 < cy < 0.30:
                header.add(compact(text))
                continue
            if (
                0.30 < cy < 0.86
                and 0.12 < left < 0.29
                and re.fullmatch(r"[a-z0]?\.\s*[a-z].*", text.casefold())
            ):
                names.append((cy * BASE_HEIGHT, text))
        if not {"no", "name", "role", "form", "morale"} <= header:
            return [], {}
        regions = {
            f"roster.{row}.squad_number": (
                55,
                round(center) - 12,
                132,
                round(center) + 12,
            )
            for row, (center, name) in enumerate(names)
        }
        evidence = (
            self.recognize(image, regions, set(regions), verify_numeric=True)
            if regions
            else {}
        )
        records = []
        for row, (center, name) in enumerate(names):
            number = parse_integer(evidence[f"roster.{row}.squad_number"]["raw_text"])
            if number is None or not 1 <= number <= 99:
                continue
            player = re.sub(r"^0\.", "O.", name)
            player = re.sub(r"^\.\s*", "", player).strip()
            if not player:
                continue
            records.append(
                {
                    "type": "player_jersey",
                    "player": player,
                    "club": profile["club"],
                    "season": None,
                    "squad_number": number,
                }
            )
        return records, evidence
