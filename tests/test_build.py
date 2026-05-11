"""Tests for manascope.build — deck drafting from EDHREC + collection."""

import json
import sqlite3
from pathlib import Path

import pytest
import pytest_mock

from manascope import build as build_mod
from manascope.build import (
    _basic_distribution,
    _format_line,
    build_decklist_text,
    select_spells,
)
from manascope.edhrec import SynergyCard

# ── Pure helpers ────────────────────────────────────────────────────────


class TestFormatLine:
    def test_renders_set_and_collector_number(self) -> None:
        card = {"name": "Greasefang, Okiba Boss", "set": "neo", "collector_number": "220"}
        assert _format_line(card) == "1 Greasefang, Okiba Boss (NEO) 220"

    def test_dfc_uses_front_face_only(self) -> None:
        card = {
            "name": "Okiba Reckoner Raid // Nezumi Road Captain",
            "set": "neo",
            "collector_number": "117",
        }
        assert _format_line(card) == "1 Okiba Reckoner Raid (NEO) 117"

    def test_uses_quantity_arg(self) -> None:
        card = {"name": "Plains", "set": "fdn", "collector_number": "282"}
        assert _format_line(card, qty=8) == "8 Plains (FDN) 282"

    def test_falls_back_when_collector_number_missing(self) -> None:
        card = {"name": "Sol Ring", "set": "c21"}
        assert _format_line(card).endswith("1")  # default cn = "1"


class TestBasicDistribution:
    def test_sums_to_total(self) -> None:
        from collections import Counter

        pips = Counter({"W": 8, "B": 12})
        result = _basic_distribution(pips, ["W", "B"], 16)
        assert sum(result.values()) == 16

    def test_pip_share_drives_distribution(self) -> None:
        from collections import Counter

        # 60% B / 40% W pips → Swamps should outnumber Plains
        pips = Counter({"W": 4, "B": 6})
        result = _basic_distribution(pips, ["W", "B"], 10)
        assert result["B"] > result["W"]
        assert sum(result.values()) == 10

    def test_zero_pips_falls_back_to_even_split(self) -> None:
        from collections import Counter

        pips: Counter[str] = Counter()
        result = _basic_distribution(pips, ["W", "B"], 10)
        assert sum(result.values()) == 10
        # Even split of 10 across 2 colours → 5/5
        assert result["W"] == 5 and result["B"] == 5

    def test_zero_total_returns_zeros(self) -> None:
        from collections import Counter

        result = _basic_distribution(Counter({"W": 1}), ["W", "B"], 0)
        assert result == {"W": 0, "B": 0}


# ── select_spells ───────────────────────────────────────────────────────


@pytest.fixture()
def cache(tmp_path: Path) -> sqlite3.Connection:
    """Minimal Scryfall cache populated with a handful of cards."""
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

    def add(name: str, *, ci: list[str], type_line: str, brawl: str = "legal") -> None:
        payload = {
            "name": name,
            "type_line": type_line,
            "color_identity": ci,
            "legalities": {"brawl": brawl, "commander": "legal"},
            "mana_cost": "",
            "set": "neo",
            "collector_number": "1",
        }
        conn.execute(
            "INSERT INTO cards (set_code, collector_number, name, full_json) VALUES (?,?,?,?)",
            ("neo", name.lower().replace(" ", "")[:8], name, json.dumps(payload)),
        )

    add("Parhelion II", ci=["W"], type_line="Legendary Artifact — Vehicle")
    add("Bone Shards", ci=["B"], type_line="Sorcery")
    add("Fireball", ci=["R"], type_line="Sorcery")  # out-of-identity
    add("Lightning Bolt", ci=["R"], type_line="Instant", brawl="not_legal")
    add("Plains", ci=["W"], type_line="Basic Land — Plains")
    conn.commit()
    return conn


def _commander() -> dict:
    return {
        "name": "Greasefang, Okiba Boss",
        "color_identity": ["B", "W"],
        "type_line": "Legendary Creature — Rat Pilot",
    }


def _rec(name: str, synergy: float = 50.0) -> SynergyCard:
    return SynergyCard(
        name=name, synergy=synergy / 100.0, inclusion=10, potential_decks=100, category="x"
    )


class TestSelectSpells:
    def test_owned_in_identity_card_is_selected(
        self, cache: sqlite3.Connection, mocker: pytest_mock.MockerFixture
    ) -> None:
        mocker.patch(
            "manascope.build.ec.all_recommended_cards",
            return_value=[_rec("Parhelion II", 90)],
        )
        owned = {"parhelion ii": {"name": "Parhelion II", "count": 1}}
        selected, unowned, not_cached = select_spells(
            _commander(), {}, owned, cache, fmt="brawl", target_count=10, top=80
        )
        assert [c["name"] for c in selected] == ["Parhelion II"]
        assert unowned == []
        assert not_cached == []

    def test_out_of_identity_is_excluded(
        self, cache: sqlite3.Connection, mocker: pytest_mock.MockerFixture
    ) -> None:
        mocker.patch(
            "manascope.build.ec.all_recommended_cards",
            return_value=[_rec("Fireball")],
        )
        owned = {"fireball": {"name": "Fireball", "count": 1}}
        selected, unowned, _ = select_spells(
            _commander(), {}, owned, cache, fmt="brawl", target_count=10, top=80
        )
        assert selected == []
        # Out-of-identity cards aren't even surfaced as wishlist candidates.
        assert unowned == []

    def test_format_illegal_card_is_excluded(
        self, cache: sqlite3.Connection, mocker: pytest_mock.MockerFixture
    ) -> None:
        mocker.patch(
            "manascope.build.ec.all_recommended_cards",
            return_value=[_rec("Lightning Bolt")],
        )
        owned = {"lightning bolt": {"name": "Lightning Bolt", "count": 1}}
        selected, _unowned, _ = select_spells(
            _commander(), {}, owned, cache, fmt="brawl", target_count=10, top=80
        )
        assert selected == []

    def test_unowned_legal_in_identity_card_goes_to_wishlist(
        self, cache: sqlite3.Connection, mocker: pytest_mock.MockerFixture
    ) -> None:
        mocker.patch(
            "manascope.build.ec.all_recommended_cards",
            return_value=[_rec("Bone Shards")],
        )
        owned: dict[str, dict] = {}
        selected, unowned, _ = select_spells(
            _commander(), {}, owned, cache, fmt="brawl", target_count=10, top=80
        )
        assert selected == []
        assert [c["name"] for c in unowned] == ["Bone Shards"]

    def test_basic_land_recommended_is_skipped(
        self, cache: sqlite3.Connection, mocker: pytest_mock.MockerFixture
    ) -> None:
        # Even if EDHREC suggests a basic, the build flow handles lands separately.
        mocker.patch(
            "manascope.build.ec.all_recommended_cards",
            return_value=[_rec("Plains")],
        )
        owned = {"plains": {"name": "Plains", "count": 4}}
        selected, _unowned, _ = select_spells(
            _commander(), {}, owned, cache, fmt="brawl", target_count=10, top=80
        )
        assert selected == []

    def test_target_count_is_respected(
        self, cache: sqlite3.Connection, mocker: pytest_mock.MockerFixture
    ) -> None:
        # Two recs, both owned & in-identity — but target_count=1 should cap at 1.
        mocker.patch(
            "manascope.build.ec.all_recommended_cards",
            return_value=[_rec("Parhelion II", 90), _rec("Bone Shards", 80)],
        )
        owned = {
            "parhelion ii": {"name": "Parhelion II", "count": 1},
            "bone shards": {"name": "Bone Shards", "count": 1},
        }
        selected, _unowned, _ = select_spells(
            _commander(), {}, owned, cache, fmt="brawl", target_count=1, top=80
        )
        assert len(selected) == 1


# ── build_decklist_text ─────────────────────────────────────────────────


class TestBuildDecklistText:
    def test_emits_brawl_headers(self) -> None:
        cmd = {"name": "Greasefang, Okiba Boss", "set": "neo", "collector_number": "220"}
        text = build_decklist_text(cmd, [], {"W": 1, "B": 1}, fmt="brawl")
        assert text.startswith("Commander\n1 Greasefang, Okiba Boss (NEO) 220\n\nDeck\n")

    def test_paper_commander_omits_headers(self) -> None:
        cmd = {"name": "Atraxa", "set": "ony", "collector_number": "1"}
        text = build_decklist_text(cmd, [], {}, fmt="commander")
        assert text.startswith("1 Atraxa (ONY) 1")
        assert "Commander\n" not in text

    def test_basics_appear_after_spells(self) -> None:
        cmd = {"name": "X", "set": "neo", "collector_number": "1"}
        spells = [{"name": "Bone Shards", "set": "neo", "collector_number": "76"}]
        text = build_decklist_text(cmd, spells, {"B": 2}, fmt="brawl")
        lines = text.strip().split("\n")
        # Basics are consolidated onto a single quantity line and follow the spells.
        assert lines[-1] == "2 Swamp (NEO) 1"
        assert "1 Bone Shards (NEO) 76" in lines

    def test_basics_are_consolidated_per_colour(self) -> None:
        cmd = {"name": "X", "set": "neo", "collector_number": "1"}
        text = build_decklist_text(cmd, [], {"W": 8, "B": 9}, fmt="brawl")
        # Exactly one line per colour, with the qty consolidated.
        assert text.count("Plains") == 1
        assert text.count("Swamp") == 1
        assert "8 Plains (NEO) 1" in text
        assert "9 Swamp (NEO) 1" in text

    def test_basics_emitted_in_wubrg_order(self) -> None:
        cmd = {"name": "X", "set": "neo", "collector_number": "1"}
        text = build_decklist_text(cmd, [], {"G": 1, "W": 1, "B": 1, "U": 1, "R": 1}, fmt="brawl")
        lines = [ln for ln in text.strip().split("\n") if ln and ln[0].isdigit()]
        # Skip the commander line; remaining lines should be in WUBRG order.
        basic_names = [ln.split()[1] for ln in lines[1:]]
        assert basic_names == ["Plains", "Island", "Swamp", "Mountain", "Forest"]


# ── run() integration: error paths ──────────────────────────────────────


class TestRun:
    def test_unknown_format_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="unknown format"):
            build_mod.run(
                commander_name="X",
                collection_paths=[tmp_path / "x.csv"],
                fmt="bogus",
                cache=tmp_path / "cache.db",
            )

    def test_too_many_lands_raises(self, tmp_path: Path) -> None:
        csv = tmp_path / "coll.csv"
        csv.write_text("Count,Name,Edition,Condition,Language,Foil,Tag\n", encoding="utf-8")
        with pytest.raises(ValueError, match="leaves no room"):
            build_mod.run(
                commander_name="X",
                collection_paths=[csv],
                fmt="brawl",
                lands=200,
                cache=tmp_path / "cache.db",
            )

    def test_missing_commander_raises(self, tmp_path: Path) -> None:
        csv = tmp_path / "coll.csv"
        csv.write_text("Count,Name,Edition,Condition,Language,Foil,Tag\n", encoding="utf-8")
        with pytest.raises(ValueError, match="not in Scryfall cache"):
            build_mod.run(
                commander_name="Nobody Real",
                collection_paths=[csv],
                fmt="brawl",
                cache=tmp_path / "cache.db",
            )
