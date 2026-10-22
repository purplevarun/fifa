from uuid import UUID, uuid4


REFERENCE_TABLES = {
    "source_id": "source_images",
    "match_source_id": "source_images",
    "match_id": "matches",
    "player_id": "players",
    "club_id": "clubs",
    "home_club_id": "clubs",
    "away_club_id": "clubs",
    "from_club_id": "clubs",
    "to_club_id": "clubs",
    "season_id": "seasons",
    "competition_id": "competitions",
    "competition_season_id": "competition_seasons",
    "player_match_id": "player_matches",
}


def new_id():
    return str(uuid4())


def is_uuid(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = UUID(value)
    except ValueError:
        return False
    return str(parsed) == value and parsed.int != 0


def resolve_id(table, value):
    if value is None or is_uuid(value):
        return value
    raise ValueError(f"{table} identifier must be a canonical UUID: {value!r}")


def normalize_references(value):
    if isinstance(value, list):
        return [normalize_references(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for field, item in value.items():
        if field in REFERENCE_TABLES:
            result[field] = resolve_id(REFERENCE_TABLES[field], item)
        else:
            result[field] = normalize_references(item)
    return result
