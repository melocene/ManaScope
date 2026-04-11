"""Tests for manascope.collection — loading, name indexing, rarity lookup."""

import json
import sqlite3
from pathlib import Path

import pytest

from manascope.collection import (
    BASIC_LANDS,
    RARITY_ORDER,
    load_collection,
    load_collection_names,
    load_collections,
    load_collections_names,
    lookup_rarity,
)

# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture()
def collection_file(tmp_path: Path) -> Path:
    """Write a minimal mtga_collection.json and return its path."""
    data = {
        "cards": [
            {"name": "Sol Ring", "count": 1, "set": "C21", "cn": "263"},
            {"name": "Plains", "count": 4, "set": "ONE", "cn": "267"},
            {
                "name": "Archangel Avacyn // Avacyn, the Purifier",
                "count": 1,
                "set": "SOI",
                "cn": "5",
            },
            {"name": "Lightning Bolt", "count": 2, "set": "M10", "cn": "146"},
        ],
    }
    p = tmp_path / "mtga_collection.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


@pytest.fixture()
def empty_collection_file(tmp_path: Path) -> Path:
    p = tmp_path / "empty.json"
    p.write_text(json.dumps({"cards": []}), encoding="utf-8")
    return p


@pytest.fixture()
def cache_db(tmp_path: Path) -> sqlite3.Connection:
    """Create an in-memory-style SQLite DB with a couple of card rows."""
    db_path = tmp_path / "cache.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE cards (
            set_code         TEXT NOT NULL,
            collector_number TEXT NOT NULL,
            name             TEXT NOT NULL,
            mana_cost        TEXT NOT NULL DEFAULT '',
            full_json        TEXT NOT NULL,
            fetched_at       TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (set_code, collector_number)
        )
        """
    )
    conn.execute("CREATE INDEX idx_cards_name ON cards (name COLLATE NOCASE)")
    # Insert a normal card
    conn.execute(
        "INSERT INTO cards (set_code, collector_number, name, full_json) VALUES (?, ?, ?, ?)",
        (
            "c21",
            "263",
            "Sol Ring",
            json.dumps({"name": "Sol Ring", "rarity": "uncommon"}),
        ),
    )
    # Insert a DFC card
    conn.execute(
        "INSERT INTO cards (set_code, collector_number, name, full_json) VALUES (?, ?, ?, ?)",
        (
            "soi",
            "5",
            "Archangel Avacyn // Avacyn, the Purifier",
            json.dumps({"name": "Archangel Avacyn // Avacyn, the Purifier", "rarity": "mythic"}),
        ),
    )
    # Insert a card with missing rarity
    conn.execute(
        "INSERT INTO cards (set_code, collector_number, name, full_json) VALUES (?, ?, ?, ?)",
        ("m10", "146", "Lightning Bolt", json.dumps({"name": "Lightning Bolt"})),
    )
    conn.commit()
    yield conn
    conn.close()


# ── Constants ────────────────────────────────────────────────────────────


class TestConstants:
    def test_basic_lands(self) -> None:
        assert {"plains", "island", "swamp", "mountain", "forest"} == BASIC_LANDS

    def test_rarity_order(self) -> None:
        assert RARITY_ORDER == ["mythic", "rare", "uncommon", "common"]


# ── load_collection ──────────────────────────────────────────────────────


class TestLoadCollection:
    def test_loads_cards(self, collection_file: Path) -> None:
        coll = load_collection(collection_file)
        assert "sol ring" in coll
        assert "plains" in coll
        assert "lightning bolt" in coll

    def test_dfc_front_face_indexed(self, collection_file: Path) -> None:
        coll = load_collection(collection_file)
        # Full DFC name should be present
        assert "archangel avacyn // avacyn, the purifier" in coll
        # Front face alone should also be indexed
        assert "archangel avacyn" in coll

    def test_returns_entry_dicts(self, collection_file: Path) -> None:
        coll = load_collection(collection_file)
        entry = coll["sol ring"]
        assert entry["name"] == "Sol Ring"
        assert entry["count"] == 1

    def test_empty_collection(self, empty_collection_file: Path) -> None:
        coll = load_collection(empty_collection_file)
        assert coll == {}

    def test_front_face_does_not_overwrite_explicit(self, tmp_path: Path) -> None:
        """If a front-face-only card AND a DFC exist, setdefault preserves the first."""
        data = {
            "cards": [
                {"name": "Avacyn", "count": 1},
                {"name": "Avacyn // Purifier", "count": 2},
            ],
        }
        p = tmp_path / "c.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        coll = load_collection(p)
        # "avacyn" was first inserted directly, DFC setdefault should not overwrite
        assert coll["avacyn"]["count"] == 1


# ── load_collection_names ────────────────────────────────────────────────


class TestLoadCollectionNames:
    def test_returns_set_of_strings(self, collection_file: Path) -> None:
        names = load_collection_names(collection_file)
        assert isinstance(names, set)
        assert "sol ring" in names
        assert "plains" in names

    def test_dfc_front_face(self, collection_file: Path) -> None:
        names = load_collection_names(collection_file)
        assert "archangel avacyn // avacyn, the purifier" in names
        assert "archangel avacyn" in names

    def test_empty(self, empty_collection_file: Path) -> None:
        names = load_collection_names(empty_collection_file)
        assert names == set()

    def test_count(self, collection_file: Path) -> None:
        names = load_collection_names(collection_file)
        # 4 cards + 1 DFC front face = 5 names
        assert len(names) == 5


# ── lookup_rarity ────────────────────────────────────────────────────────


class TestLookupRarity:
    def test_exact_match(self, cache_db: sqlite3.Connection) -> None:
        assert lookup_rarity(cache_db, "Sol Ring") == "uncommon"

    def test_case_insensitive(self, cache_db: sqlite3.Connection) -> None:
        assert lookup_rarity(cache_db, "sol ring") == "uncommon"
        assert lookup_rarity(cache_db, "SOL RING") == "uncommon"

    def test_dfc_full_name(self, cache_db: sqlite3.Connection) -> None:
        assert lookup_rarity(cache_db, "Archangel Avacyn // Avacyn, the Purifier") == "mythic"

    def test_dfc_front_face_fallback(self, cache_db: sqlite3.Connection) -> None:
        """Looking up just the front face should fall back to LIKE match."""
        assert lookup_rarity(cache_db, "Archangel Avacyn") == "mythic"

    def test_missing_rarity_field(self, cache_db: sqlite3.Connection) -> None:
        """Card cached but rarity key absent in JSON → 'unknown'."""
        assert lookup_rarity(cache_db, "Lightning Bolt") == "unknown"

    def test_not_cached(self, cache_db: sqlite3.Connection) -> None:
        assert lookup_rarity(cache_db, "Nonexistent Card") == "unknown"

    def test_malformed_json(self, cache_db: sqlite3.Connection) -> None:
        """If full_json is not valid JSON, should return 'unknown'."""
        cache_db.execute(
            "INSERT INTO cards (set_code, collector_number, name, full_json) VALUES (?, ?, ?, ?)",
            ("xxx", "1", "Bad Card", "not json"),
        )
        cache_db.commit()
        assert lookup_rarity(cache_db, "Bad Card") == "unknown"


# ── load_collection (CSV) ────────────────────────────────────────────────

MANABOX_HEADER = (
    "Name,Set code,Set name,Collector number,Foil,Rarity,"
    "Quantity,ManaBox ID,Scryfall ID,Purchase price,"
    "Misprint,Altered,Condition,Language,Purchase price currency"
)


def _csv_row(
    name: str,
    quantity: int = 1,
    set_code: str = "ONE",
    cn: str = "1",
) -> str:
    """Build a single ManaBox-style CSV data row."""
    # Quote the name to handle commas in DFC names like "A // B, C"
    quoted = f'"{name}"' if "," in name else name
    return f"{quoted},{set_code},,{cn},,uncommon,{quantity},,,,,,,en,"


@pytest.fixture()
def csv_collection_file(tmp_path: Path) -> Path:
    """Write a minimal ManaBox-format CSV and return its path."""
    lines = [
        MANABOX_HEADER,
        _csv_row("Sol Ring", quantity=1, set_code="C21", cn="263"),
        _csv_row("Plains", quantity=4, set_code="ONE", cn="267"),
        _csv_row(
            "Archangel Avacyn // Avacyn, the Purifier",
            quantity=1,
            set_code="SOI",
            cn="5",
        ),
        _csv_row("Lightning Bolt", quantity=2, set_code="M10", cn="146"),
    ]
    p = tmp_path / "manabox_collection.csv"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


@pytest.fixture()
def empty_csv_file(tmp_path: Path) -> Path:
    """CSV with headers only, no data rows."""
    p = tmp_path / "empty.csv"
    p.write_text(MANABOX_HEADER + "\n", encoding="utf-8")
    return p


class TestLoadCsvCollection:
    def test_loads_cards(self, csv_collection_file: Path) -> None:
        coll = load_collection(csv_collection_file)
        assert "sol ring" in coll
        assert "plains" in coll
        assert "lightning bolt" in coll

    def test_quantity_used_for_count(self, csv_collection_file: Path) -> None:
        coll = load_collection(csv_collection_file)
        assert coll["plains"]["count"] == 4
        assert coll["lightning bolt"]["count"] == 2
        assert coll["sol ring"]["count"] == 1

    def test_dfc_front_face_indexed(self, csv_collection_file: Path) -> None:
        coll = load_collection(csv_collection_file)
        assert "archangel avacyn // avacyn, the purifier" in coll
        assert "archangel avacyn" in coll

    def test_zero_quantity_skipped(self, tmp_path: Path) -> None:
        lines = [
            MANABOX_HEADER,
            _csv_row("Ghost Card", quantity=0),
            _csv_row("Real Card", quantity=1),
        ]
        p = tmp_path / "zeros.csv"
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        coll = load_collection(p)
        assert "ghost card" not in coll
        assert "real card" in coll

    def test_mtga_count_column(self, tmp_path: Path) -> None:
        """MTGA-style CSV uses 'Count' instead of 'Quantity'."""
        header = "Name,Count"
        lines = [
            header,
            "Sol Ring,1",
            "Lightning Bolt,3",
        ]
        p = tmp_path / "mtga.csv"
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        coll = load_collection(p)
        assert "sol ring" in coll
        assert coll["sol ring"]["count"] == 1
        assert coll["lightning bolt"]["count"] == 3

    def test_empty_csv(self, empty_csv_file: Path) -> None:
        coll = load_collection(empty_csv_file)
        assert coll == {}


class TestLoadCsvCollectionNames:
    def test_returns_set_of_strings(self, csv_collection_file: Path) -> None:
        names = load_collection_names(csv_collection_file)
        assert isinstance(names, set)
        assert "sol ring" in names
        assert "plains" in names

    def test_dfc_front_face(self, csv_collection_file: Path) -> None:
        names = load_collection_names(csv_collection_file)
        assert "archangel avacyn // avacyn, the purifier" in names
        assert "archangel avacyn" in names

    def test_count(self, csv_collection_file: Path) -> None:
        names = load_collection_names(csv_collection_file)
        # 4 cards + 1 DFC front face = 5 names
        assert len(names) == 5

    def test_empty(self, empty_csv_file: Path) -> None:
        names = load_collection_names(empty_csv_file)
        assert names == set()


# ── load_collections (multi-file merge) ──────────────────────────────────


@pytest.fixture()
def csv_collection_a(tmp_path: Path) -> Path:
    """First CSV: Sol Ring (x1), Plains (x4), Lightning Bolt (x2)."""
    lines = [
        MANABOX_HEADER,
        _csv_row("Sol Ring", quantity=1, set_code="C21", cn="263"),
        _csv_row("Plains", quantity=4, set_code="ONE", cn="267"),
        _csv_row("Lightning Bolt", quantity=2, set_code="M10", cn="146"),
    ]
    p = tmp_path / "collection_a.csv"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


@pytest.fixture()
def csv_collection_b(tmp_path: Path) -> Path:
    """Second CSV: Sol Ring (x1), Swords to Plowshares (x3), DFC card (x1)."""
    lines = [
        MANABOX_HEADER,
        _csv_row("Sol Ring", quantity=1, set_code="C20", cn="217"),
        _csv_row("Swords to Plowshares", quantity=3, set_code="ICE", cn="54"),
        _csv_row(
            "Archangel Avacyn // Avacyn, the Purifier",
            quantity=1,
            set_code="SOI",
            cn="5",
        ),
    ]
    p = tmp_path / "collection_b.csv"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


class TestLoadCollections:
    def test_single_file_delegates(self, csv_collection_a: Path) -> None:
        """A single-element list behaves identically to load_collection."""
        multi = load_collections([csv_collection_a])
        single = load_collection(csv_collection_a)
        assert multi == single

    def test_merges_unique_cards(self, csv_collection_a: Path, csv_collection_b: Path) -> None:
        coll = load_collections([csv_collection_a, csv_collection_b])
        assert "lightning bolt" in coll
        assert "swords to plowshares" in coll
        assert "plains" in coll

    def test_sums_counts_for_overlapping_cards(
        self, csv_collection_a: Path, csv_collection_b: Path
    ) -> None:
        coll = load_collections([csv_collection_a, csv_collection_b])
        # Sol Ring appears in both files with quantity 1 each
        assert coll["sol ring"]["count"] == 2

    def test_non_overlapping_counts_preserved(
        self, csv_collection_a: Path, csv_collection_b: Path
    ) -> None:
        coll = load_collections([csv_collection_a, csv_collection_b])
        assert coll["plains"]["count"] == 4
        assert coll["swords to plowshares"]["count"] == 3
        assert coll["lightning bolt"]["count"] == 2

    def test_dfc_front_face_indexed_across_files(
        self, csv_collection_a: Path, csv_collection_b: Path
    ) -> None:
        """DFC front-face key should be present when DFC is in a secondary file."""
        coll = load_collections([csv_collection_a, csv_collection_b])
        assert "archangel avacyn // avacyn, the purifier" in coll
        assert "archangel avacyn" in coll

    def test_empty_file_does_not_break_merge(
        self, csv_collection_a: Path, empty_csv_file: Path
    ) -> None:
        coll = load_collections([csv_collection_a, empty_csv_file])
        assert "sol ring" in coll
        assert coll["sol ring"]["count"] == 1

    def test_two_empty_files(self, empty_csv_file: Path, tmp_path: Path) -> None:
        empty2 = tmp_path / "empty2.csv"
        empty2.write_text(MANABOX_HEADER + "\n", encoding="utf-8")
        coll = load_collections([empty_csv_file, empty2])
        assert coll == {}

    def test_does_not_mutate_source_dicts(
        self, csv_collection_a: Path, csv_collection_b: Path
    ) -> None:
        """Merging should not modify the dict returned by load_collection."""
        original = load_collection(csv_collection_a)
        original_sol_count = original["sol ring"]["count"]
        load_collections([csv_collection_a, csv_collection_b])
        assert original["sol ring"]["count"] == original_sol_count

    def test_mixed_csv_and_json(self, csv_collection_a: Path, collection_file: Path) -> None:
        """Merge works across different file formats (CSV + JSON)."""
        coll = load_collections([csv_collection_a, collection_file])
        # Sol Ring is in both files (qty 1 each)
        assert coll["sol ring"]["count"] == 2
        # CSV-only card
        assert "plains" in coll
        # JSON collection also has Plains (qty 4) — plus CSV (qty 4) = 8
        assert coll["plains"]["count"] == 8
        # JSON-only DFC
        assert "archangel avacyn" in coll

    def test_three_files(
        self, csv_collection_a: Path, csv_collection_b: Path, tmp_path: Path
    ) -> None:
        """Verify merging works with more than two files."""
        lines = [
            MANABOX_HEADER,
            _csv_row("Sol Ring", quantity=5, set_code="2XM", cn="274"),
        ]
        p = tmp_path / "collection_c.csv"
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        coll = load_collections([csv_collection_a, csv_collection_b, p])
        # 1 + 1 + 5
        assert coll["sol ring"]["count"] == 7


class TestLoadCollectionsNames:
    def test_returns_union_of_names(self, csv_collection_a: Path, csv_collection_b: Path) -> None:
        names = load_collections_names([csv_collection_a, csv_collection_b])
        assert isinstance(names, set)
        assert "sol ring" in names
        assert "lightning bolt" in names
        assert "swords to plowshares" in names
        assert "plains" in names
        assert "archangel avacyn" in names

    def test_single_file_matches_original(self, csv_collection_a: Path) -> None:
        multi = load_collections_names([csv_collection_a])
        single = load_collection_names(csv_collection_a)
        assert multi == single

    def test_empty_files(self, empty_csv_file: Path, tmp_path: Path) -> None:
        empty2 = tmp_path / "empty2.csv"
        empty2.write_text(MANABOX_HEADER + "\n", encoding="utf-8")
        names = load_collections_names([empty_csv_file, empty2])
        assert names == set()
