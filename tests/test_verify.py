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


class TestVerifyDecklistPrintings:
    """Coverage for the ``owned_printings`` parameter that performs an
    exact (name, set, collector#) check on top of the name-only ownership
    check. Closes a long-standing bug where ``verify`` reported deckists
    as fully owned even when their listed printings weren't in the
    collection (e.g. ``Sol Ring (CMM) 410`` passing because *some* Sol
    Ring was owned).
    """

    def test_owned_printing_passes_clean(self, cache: sqlite3.Connection) -> None:
        """Decklist whose (name, set, cn) tuple is in owned_printings → no errors."""
        entries = [
            (
                1,
                CardIdentifier(
                    set_code="NEO", collector_number="220", name="Greasefang, Okiba Boss"
                ),
            )
        ]
        owned = {"greasefang, okiba boss"}
        owned_printings = {("greasefang, okiba boss", "neo", "220")}
        result = verify_decklist(entries, owned, cache, owned_printings=owned_printings)
        assert result["missing_count"] == 0
        assert result["wrong_printing_count"] == 0
        assert result["wrong_printing"] == []

    def test_wrong_printing_flagged(self, cache: sqlite3.Connection) -> None:
        """Card name owned but printing differs → reported under wrong_printing.

        This is the regression test for the original bug: prior to this fix
        the deck would pass verify with missing_count=0 because the name
        "Sol Ring" matched the owned name set, despite the (CMM, 410)
        printing being unowned.
        """
        entries = [(1, CardIdentifier(set_code="CMM", collector_number="410", name="Sol Ring"))]
        owned = {"sol ring"}
        # Collection actually has the ECC 58 printing, not CMM 410.
        owned_printings = {("sol ring", "ecc", "58")}
        result = verify_decklist(entries, owned, cache, owned_printings=owned_printings)
        assert result["missing_count"] == 0  # name still considered owned
        assert result["wrong_printing_count"] == 1
        assert result["wrong_printing"] == [
            {"name": "Sol Ring", "set": "CMM", "collector_number": "410"}
        ]

    def test_missing_card_not_double_reported(self, cache: sqlite3.Connection) -> None:
        """Cards whose names aren't owned at all stay in missing, never wrong_printing.

        Avoids confusing duplicate noise where a totally-missing card would
        otherwise also fail the printing check.
        """
        entries = [(1, CardIdentifier(set_code="FOO", collector_number="1", name="Phantom Card"))]
        owned: set[str] = set()
        owned_printings: set[tuple[str, str, str]] = set()
        result = verify_decklist(entries, owned, cache_conn=None, owned_printings=owned_printings)
        assert result["missing_count"] == 1
        assert result["wrong_printing_count"] == 0
        assert result["missing"][0]["name"] == "Phantom Card"

    def test_dfc_front_face_matches_printing(self, cache: sqlite3.Connection) -> None:
        """Decklists often spell only the front face of a DFC; matching against
        either the full or front-face name in owned_printings should succeed.
        """
        entries = [
            (
                1,
                CardIdentifier(
                    set_code="NEO", collector_number="220", name="Greasefang, Okiba Boss"
                ),
            )
        ]
        owned = {"greasefang, okiba boss"}
        # Collection key uses the full DFC name; verify still matches.
        owned_printings = {("greasefang, okiba boss // some backside", "neo", "220")}
        # And the front-face form must also work — both keys are commonly
        # indexed by the loader.
        owned_printings.add(("greasefang, okiba boss", "neo", "220"))
        result = verify_decklist(entries, owned, cache, owned_printings=owned_printings)
        assert result["wrong_printing_count"] == 0

    def test_no_owned_printings_skips_check(self, cache: sqlite3.Connection) -> None:
        """When owned_printings is None (default), printing-level keys are absent
        from the result — preserves backward compatibility with MTGA exports
        and existing callers that only have name data.
        """
        entries = [(1, CardIdentifier(set_code="CMM", collector_number="410", name="Sol Ring"))]
        owned = {"sol ring"}
        result = verify_decklist(entries, owned, cache)
        assert "wrong_printing" not in result
        assert "wrong_printing_count" not in result
        assert result["missing_count"] == 0

    def test_collector_number_normalized(self, cache: sqlite3.Connection) -> None:
        """Collector numbers compare case-insensitively and ignore surrounding
        whitespace so casing/format quirks don't cause false negatives.
        """
        entries = [
            (1, CardIdentifier(set_code="PBRO", collector_number="170S", name="Awaken the Woods"))
        ]
        owned = {"awaken the woods"}
        owned_printings = {("awaken the woods", "pbro", "170s")}
        result = verify_decklist(entries, owned, cache_conn=None, owned_printings=owned_printings)
        assert result["wrong_printing_count"] == 0
