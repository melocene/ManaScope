"""Tests for manascope.verify — decklist ownership cross-check."""

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from manascope.deck import CardIdentifier
from manascope.verify import verify_decklist


@pytest.fixture()
def cache(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    db_path = tmp_path / "cache.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE cards (
            set_code         TEXT NOT NULL,
            collector_number TEXT NOT NULL,
            name             TEXT NOT NULL,
            mana_cost        TEXT NOT NULL DEFAULT '',
            full_json        TEXT NOT NULL,
            fetched_at       TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (set_code, collector_number)
        );
        CREATE INDEX idx_cards_name ON cards (name COLLATE NOCASE);
        """
    )
    rows = [
        ("neo", "220", "Greasefang, Okiba Boss", "rare"),
        ("neo", "16", "Hotshot Mechanic", "uncommon"),
        ("war", "26", "Parhelion II", "rare"),
        ("j21", "298", "Bone Shards", "common"),
    ]
    for set_code, cn, name, rarity in rows:
        conn.execute(
            "INSERT INTO cards (set_code, collector_number, name, full_json) VALUES (?,?,?,?)",
            (set_code, cn, name, json.dumps({"name": name, "rarity": rarity})),
        )
    conn.commit()
    yield conn
    conn.close()


def _entry(name: str, set_code: str = "neo", cn: str = "1") -> tuple[int, CardIdentifier]:
    return (1, CardIdentifier(set_code=set_code, collector_number=cn, name=name))


class TestVerifyDecklist:
    def test_all_owned(self, cache: sqlite3.Connection) -> None:
        entries = [_entry("Greasefang, Okiba Boss"), _entry("Bone Shards")]
        owned = {"greasefang, okiba boss", "bone shards"}
        result = verify_decklist(entries, owned, cache)
        assert result["missing_count"] == 0
        assert result["missing"] == []
        assert result["checked"] == 2

    def test_missing_card_reported_with_rarity(self, cache: sqlite3.Connection) -> None:
        entries = [_entry("Hotshot Mechanic")]
        owned: set[str] = set()
        result = verify_decklist(entries, owned, cache)
        assert result["missing_count"] == 1
        assert result["missing"] == [{"name": "Hotshot Mechanic", "rarity": "uncommon"}]
        assert result["by_rarity"]["uncommon"] == ["Hotshot Mechanic"]

    def test_basic_lands_never_missing(self, cache: sqlite3.Connection) -> None:
        entries = [_entry("Plains")]
        owned: set[str] = set()
        result = verify_decklist(entries, owned, cache)
        # Basics are owned by definition; checked count is 0 because they're skipped.
        assert result["checked"] == 0
        assert result["missing_count"] == 0

    def test_dfc_front_face_match(self, cache: sqlite3.Connection) -> None:
        entries = [_entry("Greasefang, Okiba Boss // Some Backside")]
        owned = {"greasefang, okiba boss"}  # only front face indexed
        result = verify_decklist(entries, owned, cache)
        assert result["missing_count"] == 0

    def test_unknown_rarity_when_no_cache(self) -> None:
        entries = [_entry("Phantom Card")]
        owned: set[str] = set()
        result = verify_decklist(entries, owned, cache_conn=None)
        assert result["missing"] == [{"name": "Phantom Card", "rarity": "unknown"}]

    def test_by_rarity_order_canonical(self, cache: sqlite3.Connection) -> None:
        # Mythic > rare > uncommon > common; verify the dict iterates in that order.
        # Add a mythic to the cache for this test.
        cache.execute(
            "INSERT INTO cards (set_code, collector_number, name, full_json) VALUES (?,?,?,?)",
            ("xxx", "1", "Big Mythic", json.dumps({"name": "Big Mythic", "rarity": "mythic"})),
        )
        cache.commit()
        entries = [
            _entry("Big Mythic"),
            _entry("Bone Shards"),
            _entry("Hotshot Mechanic"),
            _entry("Parhelion II"),
        ]
        result = verify_decklist(entries, set(), cache)
        # RARITY_ORDER is mythic, rare, uncommon, common — matches dict order.
        assert list(result["by_rarity"].keys()) == ["mythic", "rare", "uncommon", "common"]

    def test_missing_list_sorted(self, cache: sqlite3.Connection) -> None:
        entries = [_entry("Parhelion II"), _entry("Bone Shards"), _entry("Hotshot Mechanic")]
        result = verify_decklist(entries, set(), cache)
        names = [m["name"] for m in result["missing"]]
        assert names == sorted(names)
