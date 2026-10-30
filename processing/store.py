"""In-memory records with Python validation and JSON-only diagnostic persistence.

The store is working memory, not an input to a fresh processing run. Screenshots
are always re-extracted; diagnostics are loaded only by explicit maintenance tools.
"""

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from . import SCHEMA_VERSION
from .identifiers import new_id
from .record_schema import DEFINITIONS, validate_field, validate_record

COMPETITIONS = (
    ("European International Cup", "cup", True),
    ("Invitational Cup", "cup", True),
    ("EFL League Two", "league", False),
    ("EFL League One", "league", False),
    ("EFL Championship", "league", False),
    ("Premier League", "league", False),
    ("EFL Championship Play-Offs", "cup", False),
    ("UEFA Champions League", "cup", False),
    ("UEFA Europa League", "cup", False),
    ("EFL League Two Play-Offs", "cup", False),
    ("EFL League One Play-Offs", "cup", False),
    ("Carabao Cup", "cup", False),
    ("Checkatrade Trophy", "cup", False),
    ("FA Cup", "cup", False),
)
EXPORT_TABLES = (
    "players",
    "clubs",
    "seasons",
    "competitions",
    "competition_seasons",
    "matches",
    "team_matches",
    "player_matches",
    "player_snapshots",
    "player_jerseys",
    "player_competition_snapshots",
    "player_transfers",
    "competition_events",
    "match_sources",
    "player_match_sources",
)


def json_text(value):
    return json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + "\n"


def write_json(path, value, overwrite=True):
    path = Path(path)
    serialized = json_text(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite:
        with path.open("x", encoding="utf-8") as output:
            output.write(serialized)
        return
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as output:
            temporary_path = Path(output.name)
            output.write(serialized)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


class Store:
    def __init__(self, *, seed=True):
        self._tables = {table: {} for table in DEFINITIONS}
        self._indexes = {
            table: {key: {} for key in definition.unique}
            for table, definition in DEFINITIONS.items()
        }
        self._transactions = []
        if seed:
            for name, kind, preseason in COMPETITIONS:
                self.insert(
                    "competitions",
                    {"name": name, "kind": kind, "is_preseason": preseason},
                )

    def rows(self, table, **filters):
        definition = DEFINITIONS[table]
        for key in definition.unique:
            if all(field in filters for field in key):
                values = tuple(filters[field] for field in key)
                if None not in values:
                    primary = self._indexes[table][key].get(values)
                    row = self._tables[table].get(primary)
                    return (
                        [dict(row)]
                        if row
                        and all(row[field] == value for field, value in filters.items())
                        else []
                    )
        return [
            dict(row)
            for row in self._tables[table].values()
            if all(row[field] == value for field, value in filters.items())
        ]

    def find(self, table, **filters):
        return next(iter(self.rows(table, **filters)), None)

    def get(self, table, key):
        primary = key if isinstance(key, tuple) else (key,)
        row = self._tables[table].get(primary)
        return dict(row) if row is not None else None

    def count(self, table, **filters):
        return len(self.rows(table, **filters)) if filters else len(self._tables[table])

    def latest_review(self, source_id):
        return max(
            self.rows("reviews", source_id=source_id),
            key=lambda row: row["revision"],
            default=None,
        )

    def _replace(self, table, primary, row):
        old = self._tables[table].pop(primary, None)
        for key, index in self._indexes[table].items():
            if old:
                values = tuple(old[field] for field in key)
                if None not in values:
                    index.pop(values, None)
            if row is not None:
                values = tuple(row[field] for field in key)
                if None not in values:
                    index[values] = primary
        if row is not None:
            self._tables[table][primary] = row

    def _write(self, table, primary, row):
        validate_record(table, row, self)
        for key, index in self._indexes[table].items():
            values = tuple(row[field] for field in key)
            if None not in values and values in index and index[values] != primary:
                raise ValueError(f"Duplicate {table} identity: {', '.join(key)}")
        if self._transactions:
            self._transactions[-1].append(
                (table, primary, self._tables[table].get(primary))
            )
        self._replace(table, primary, row)

    def insert(self, table, values, *, ignore=False):
        definition = DEFINITIONS[table]
        unknown = set(values) - set(definition.columns)
        if unknown:
            raise ValueError(f"Unrecognized {table} fields: {sorted(unknown)}")
        row = dict.fromkeys(definition.columns)
        row.update(
            {
                key: value() if callable(value) else value
                for key, value in definition.defaults.items()
            }
        )
        if definition.primary == ("id",):
            row["id"] = new_id()
        row.update(values)
        primary = tuple(row[field] for field in definition.primary)
        existing = self.get(table, primary)
        if existing:
            if ignore:
                return existing
            raise ValueError(f"Duplicate {table} primary key")
        self._write(table, primary, row)
        return dict(row)

    def update(self, table, key, values):
        old = self.get(table, key)
        if old is None:
            raise ValueError(f"Missing {table} record: {key}")
        definition = DEFINITIONS[table]
        if any(
            field in values and values[field] != old[field]
            for field in definition.primary
        ):
            raise ValueError("Record primary keys cannot be changed")
        primary = tuple(old[field] for field in definition.primary)
        with self.transaction():
            self._write(table, primary, {**old, **values})
            if table in {"matches", "competition_seasons", "seasons"}:
                errors = self.validate()
                if errors:
                    raise ValueError(
                        "Update would invalidate related records: " + "; ".join(errors)
                    )

    def upsert(self, table, values):
        primary = tuple(values[field] for field in DEFINITIONS[table].primary)
        if self.get(table, primary) is None:
            self.insert(table, values)
        else:
            self.update(table, primary, values)

    def delete(self, table, **filters):
        removed = self.rows(table, **filters)
        with self.transaction():
            for row in removed:
                primary = tuple(row[field] for field in DEFINITIONS[table].primary)
                self._transactions[-1].append((table, primary, row))
                self._replace(table, primary, None)
            errors = self.validate()
            if errors:
                raise ValueError(
                    "Cannot delete referenced records: " + "; ".join(errors)
                )

    @contextmanager
    def transaction(self):
        changes = []
        self._transactions.append(changes)
        try:
            yield self
        except BaseException:
            for table, primary, old in reversed(changes):
                self._replace(table, primary, old)
            raise
        else:
            if len(self._transactions) > 1:
                self._transactions[-2].extend(changes)
        finally:
            self._transactions.pop()

    def validate(self):
        errors = []
        for table, records in self._tables.items():
            seen = {key: set() for key in DEFINITIONS[table].unique}
            for row in records.values():
                try:
                    validate_record(table, row, self)
                    for key, values in seen.items():
                        value = tuple(row[field] for field in key)
                        if None not in value:
                            if value in values:
                                raise ValueError(f"Duplicate {table} identity: {key}")
                            values.add(value)
                except (ValueError, TypeError, KeyError) as error:
                    errors.append(f"{table} {row.get('id', '')}: {error}")
        return errors

    def save(self, path, *, overwrite=True):
        errors = self.validate()
        if errors:
            raise ValueError("Invalid processing records: " + "; ".join(errors))
        write_json(
            path,
            {
                "format": "career-processing-diagnostics",
                "format_version": 1,
                "schema_version": SCHEMA_VERSION,
                "tables": {table: self.rows(table) for table in DEFINITIONS},
            },
            overwrite,
        )

    @classmethod
    def load(cls, path):
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        if (
            not isinstance(document, dict)
            or document.get("format") != "career-processing-diagnostics"
            or document.get("format_version") != 1
            or document.get("schema_version") != SCHEMA_VERSION
        ):
            raise ValueError("Unsupported processing diagnostics format")
        tables = document.get("tables")
        if not isinstance(tables, dict) or set(tables) != set(DEFINITIONS):
            raise ValueError("Missing or unknown diagnostic record collections")
        store = cls(seed=False)
        # Load all rows before checking references; JSON object order is not significant.
        for table, rows in tables.items():
            if not isinstance(rows, list):
                raise ValueError(f"{table} must contain a list of records")
            for row in rows:
                if not isinstance(row, dict) or set(row) != set(
                    DEFINITIONS[table].columns
                ):
                    raise ValueError(f"Malformed {table} record")
                for field, value in row.items():
                    validate_field(table, field, value)
                primary = tuple(row[field] for field in DEFINITIONS[table].primary)
                if primary in store._tables[table]:
                    raise ValueError(f"Duplicate {table} primary key")
                store._replace(table, primary, dict(row))
        errors = store.validate()
        if errors:
            raise ValueError("Invalid processing diagnostics: " + "; ".join(errors))
        return store


def insert_entity(store, table, values):
    return store.insert(table, values)["id"]
