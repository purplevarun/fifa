"""Conservative archive identity normalization and verified FIFA 19 fallbacks."""

import re
import unicodedata

IVORY_COAST = "Ivory Coast"


FIFA19_SOURCE = (
    "https://raw.githubusercontent.com/nazihkalo/FIFA19-Scouting-Analysis/"
    "6bb11107e06b8136c6ac2e1cd392878d47df0e4f/FIFA19_data.csv"
)
# FIFA 19 nationality labels from the pinned 18,207-player dataset above.
FIFA19_COUNTRIES = frozenset(
    [
        "Afghanistan",
        "Albania",
        "Algeria",
        "Andorra",
        "Angola",
        "Antigua & Barbuda",
        "Argentina",
        "Armenia",
        "Australia",
        "Austria",
        "Azerbaijan",
        "Barbados",
        "Belarus",
        "Belgium",
        "Belize",
        "Benin",
        "Bermuda",
        "Bolivia",
        "Bosnia Herzegovina",
        "Botswana",
        "Brazil",
        "Bulgaria",
        "Burkina Faso",
        "Burundi",
        "Cameroon",
        "Canada",
        "Cape Verde",
        "Central African Rep.",
        "Chad",
        "Chile",
        "China PR",
        "Colombia",
        "Comoros",
        "Congo",
        "Costa Rica",
        "Croatia",
        "Cuba",
        "Curacao",
        "Cyprus",
        "Czech Republic",
        "DR Congo",
        "Denmark",
        "Dominican Republic",
        "Ecuador",
        "Egypt",
        "El Salvador",
        "England",
        "Equatorial Guinea",
        "Eritrea",
        "Estonia",
        "Ethiopia",
        "FYR Macedonia",
        "Faroe Islands",
        "Fiji",
        "Finland",
        "France",
        "Gabon",
        "Gambia",
        "Georgia",
        "Germany",
        "Ghana",
        "Greece",
        "Grenada",
        "Guam",
        "Guatemala",
        "Guinea",
        "Guinea Bissau",
        "Guyana",
        "Haiti",
        "Honduras",
        "Hong Kong",
        "Hungary",
        "Iceland",
        "India",
        "Indonesia",
        "Iran",
        "Iraq",
        "Israel",
        "Italy",
        "Ivory Coast",
        "Jamaica",
        "Japan",
        "Jordan",
        "Kazakhstan",
        "Kenya",
        "Korea DPR",
        "Korea Republic",
        "Kosovo",
        "Kuwait",
        "Latvia",
        "Lebanon",
        "Liberia",
        "Libya",
        "Liechtenstein",
        "Lithuania",
        "Luxembourg",
        "Madagascar",
        "Mali",
        "Malta",
        "Mauritania",
        "Mauritius",
        "Mexico",
        "Moldova",
        "Montenegro",
        "Montserrat",
        "Morocco",
        "Mozambique",
        "Namibia",
        "Netherlands",
        "New Caledonia",
        "New Zealand",
        "Nicaragua",
        "Niger",
        "Nigeria",
        "Northern Ireland",
        "Norway",
        "Oman",
        "Palestine",
        "Panama",
        "Paraguay",
        "Peru",
        "Philippines",
        "Poland",
        "Portugal",
        "Puerto Rico",
        "Qatar",
        "Republic of Ireland",
        "Romania",
        "Russia",
        "Rwanda",
        "Saudi Arabia",
        "Scotland",
        "Senegal",
        "Serbia",
        "Sierra Leone",
        "Slovakia",
        "Slovenia",
        "South Africa",
        "South Sudan",
        "Spain",
        "St Kitts Nevis",
        "St Lucia",
        "Sudan",
        "Suriname",
        "Sweden",
        "Switzerland",
        "Syria",
        "S\u00e3o Tom\u00e9 & Pr\u00edncipe",
        "Tanzania",
        "Thailand",
        "Togo",
        "Trinidad & Tobago",
        "Tunisia",
        "Turkey",
        "Uganda",
        "Ukraine",
        "United Arab Emirates",
        "United States",
        "Uruguay",
        "Uzbekistan",
        "Venezuela",
        "Wales",
        "Zambia",
        "Zimbabwe",
    ]
)
POSITIONS = r"(?:GK|RWB|LWB|CDM|CAM|CB|RB|LB|CM|RM|LM|RW|LW|CF|ST|RF|LF)"


def identity_key(value):
    value = unicodedata.normalize("NFKD", value).casefold()
    return re.sub(r"[^a-z0-9]", "", value)


CLUB_NAMES = {
    identity_key(name): name
    for name in (
        "Notts County",
        "Lincoln City",
        "Crawley Town",
        "Swindon Town",
        "Port Vale",
        "Grimsby Town",
        "Doncaster",
        "Coventry City",
        "Cardiff City",
        "Derby County",
        "Swansea City",
        "Hull City",
        "Exeter City",
        "Yeovil Town",
        "Dundee FC",
        "MK Dons",
        "QPR",
        "Örebro SK",
        "Lech Poznań",
        "AJ Auxerre",
        "Sporting CP",
        "RSC Anderlecht",
        "R. Valladolid CF",
        "Angers SCO",
        "Boavista FC",
        "Fulham",
        "Leicester City",
        "Manchester City",
        "Newcastle Utd",
        "Southampton",
        "Spurs",
    )
}
# The OCR-readable ASCII spelling is the identity key for København's ø.
CLUB_NAMES[identity_key("FC Kobenhavn")] = "FC København"
# The W/E keyboard hint icons read as part of the club name on player
# performance screens (e.g. the 26 October 2021 Carabao Cup tie at the Etihad).
CLUB_NAMES[identity_key("Wmanchestercity")] = "Manchester City"
VENUE_NAMES = {
    identity_key(name): "Ivy Lane"
    for name in ("Ivy Lane", "lvy Lane", "ivy Lane", "livy Lane")
}
VENUE_NAMES[identity_key("KcoM Stadium")] = "KCOM Stadium"
COUNTRY_NAMES = {identity_key(name): name for name in FIFA19_COUNTRIES}
COUNTRY_NAMES.update({"scotand": "Scotland"})
USER_CONFIRMED_NATIONALITIES = {
    identity_key(name): country
    for name, country in (
        ("Leo Ostigard", "Norway"),
        ("Scott Cuthbert", "Scotland"),
        ("Nathan Delfouneso", "England"),
        ("Takefusa Kubo", "Japan"),
    )
}
# Explicit archive identities, NOT fuzzy surname/initial matches. In particular,
# FIFA 19 contains two different M. James players with different nationalities.
FIFA19_PLAYERS = {
    identity_key(name): (player_id, database_name, country)
    for name, player_id, database_name, country in (
        ("Matty James", 186139, "M. James", "England"),
        ("Tosin Adarabioyo", 222104, "T. Adarabioyo", "England"),
        ("Dominic Calvert-Lewin", 221479, "D. Calvert-Lewin", "England"),
        ("Seydou Doumbia", 188428, "S. Doumbia", IVORY_COAST),
        ("Sammy Ameobi", 203537, "S. Ameobi", "England"),
        ("Thiago Almada", 245371, "T. Almada", "Argentina"),
        ("Abdoulaye Dabo", 241403, "A. Dabo", "France"),
        ("Lionel Messi", 158023, "L. Messi", "Argentina"),
    )
}


def canonical_club_name(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("A non-empty club name is required")
    name = " ".join(value.split())
    return CLUB_NAMES.get(identity_key(name), name)


def canonical_venue_name(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("A non-empty venue name is required")
    name = " ".join(value.split())
    key = identity_key(name)
    if key in VENUE_NAMES:
        return VENUE_NAMES[key]
    if re.fullmatch(r"[il1]{1,2}vylane", key):
        return "Ivy Lane"
    return name


def normalize_nationality(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("A nationality must be a string")  # noqa: TRY004 - importer validation contract
    text = " ".join(value.split())
    text = re.sub(r"^(?:Age|ge)\s*+:?\s*+\d++\s*+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(?:^|\s)\d+(?=\s|$)", " ", text).strip()
    key = identity_key(text)
    if key in COUNTRY_NAMES:
        return COUNTRY_NAMES[key]
    # Only remove known separator/flag OCR fragments, not arbitrary words or
    # valid country initials (Iceland, India, Italy, Ivory Coast, etc.).
    for suffix in sorted(COUNTRY_NAMES, key=len, reverse=True):
        if key.endswith(suffix) and re.fullmatch(
            r"[i1lxhdep]{1,3}", key[: -len(suffix)]
        ):
            return COUNTRY_NAMES[suffix]
    return None


def normalize_positions(value):
    if not isinstance(value, str):
        return None
    matched = re.fullmatch(
        rf"[\s●•]*({POSITIONS}(?:\s*/\s*{POSITIONS})*)\s*[|Il]?\s*",
        value,
        re.IGNORECASE,
    )
    return re.sub(r"\s+", "", matched.group(1)).upper() if matched else None


def resolve_nationality(player, value=None):
    """Return (country, fallback provenance); readable source values win."""
    if country := normalize_nationality(value):
        return country, None
    key = identity_key(player)
    if country := USER_CONFIRMED_NATIONALITIES.get(key):
        return country, {
            "method": "user_confirmed_player_nationality",
            "player": player,
        }
    if reference := FIFA19_PLAYERS.get(key):
        player_id, database_name, country = reference
        return country, {
            "method": "verified_fifa19_nationality",
            "fifa19_id": player_id,
            "database_name": database_name,
            "source": FIFA19_SOURCE,
        }
    return None, None
