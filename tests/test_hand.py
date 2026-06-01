"""Tests for manascope.hand — opening-hand simulator."""

from __future__ import annotations

import json
import random
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from manascope.deck import CardIdentifier
from manascope.hand import (
    DEFAULT_HAND_SIZE,
    aggregate,
    build_library,
    decide_keep,
    hand_summary,
    run,
    simulate_one,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _land(name: str = "Plains") -> dict:
    """Build a minimal land card dict."""
    return {
        "name": name,
        "type_line": "Basic Land — Plains",
        "mana_cost": "",
        "cmc": 0.0,
    }


def _spell(name: str = "Bolt", cmc: float = 1.0, type_line: str = "Instant") -> dict:
    return {
        "name": name,
        "type_line": type_line,
        "mana_cost": "{R}",
        "cmc": cmc,
    }


def _ident(name: str, set_code: str = "tst", cn: str = "1") -> CardIdentifier:
    return CardIdentifier(set_code=set_code, collector_number=cn, name=name)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestBuildLibrary:
    def test_commander_removed_from_library(self) -> None:
        commander = _spell("Ulalek", cmc=5.0, type_line="Legendary Creature — Eldrazi")
        spell = _spell("Bolt")
        entries = [
            (1, _ident("Ulalek", "m3c", "4")),
            (1, _ident("Bolt", "tst", "1")),
        ]
        card_map = {("m3c", "4"): commander, ("tst", "1"): spell}
        library, cmd = build_library(entries, card_map)
        assert cmd is commander
        # Commander's qty was 1 and it was removed -> only Bolt in library.
        assert library == [spell]

    def test_unknown_cards_skipped(self) -> None:
        commander = _spell("Ulalek")
        entries = [
            (1, _ident("Ulalek", "m3c", "4")),
            (1, _ident("Missing", "xxx", "1")),
        ]
        card_map = {("m3c", "4"): commander}
        library, cmd = build_library(entries, card_map)
        assert cmd is commander
        assert library == []

    def test_quantities_expanded(self) -> None:
        commander = _spell("Cmdr")
        plains = _land()
        entries = [
            (1, _ident("Cmdr", "tst", "0")),
            (4, _ident("Plains", "tst", "1")),
        ]
        card_map = {("tst", "0"): commander, ("tst", "1"): plains}
        library, _ = build_library(entries, card_map)
        assert library == [plains, plains, plains, plains]


class TestHandSummary:
    def test_counts_lands_and_spells(self) -> None:
        hand = [_land(), _land(), _spell(cmc=2), _spell(cmc=4)]
        summary = hand_summary(hand)
        assert summary["lands"] == 2
        assert summary["spells"] == 2
        assert summary["avg_spell_cmc"] == 3.0

    def test_all_lands(self) -> None:
        hand = [_land(), _land(), _land()]
        summary = hand_summary(hand)
        assert summary["lands"] == 3
        assert summary["spells"] == 0
        assert summary["avg_spell_cmc"] == 0.0


class TestDecideKeep:
    def test_none_means_always_keep(self) -> None:
        assert decide_keep([_land()], None) is True

    def test_keep_when_in_window(self) -> None:
        hand = [_land(), _land(), _spell(), _spell(), _spell(), _spell(), _spell()]
        assert decide_keep(hand, mulligan_to=5) is True

    def test_mulligan_below_floor(self) -> None:
        hand = [_land()] + [_spell()] * 6  # 1 land
        assert decide_keep(hand, mulligan_to=5) is False

    def test_mulligan_above_ceiling(self) -> None:
        hand = [_land()] * 6 + [_spell()]  # 6 lands
        assert decide_keep(hand, mulligan_to=5) is False


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------


class TestSimulateOne:
    def test_returns_hand_size(self) -> None:
        library = [_land() for _ in range(40)] + [_spell() for _ in range(60)]
        result = simulate_one(library, rng=random.Random(0))
        assert len(result.hand) == DEFAULT_HAND_SIZE
        assert result.mulligans == 0
        assert result.cards_bottomed == 0

    def test_empty_library_returns_empty(self) -> None:
        result = simulate_one([], rng=random.Random(0))
        assert result.hand == []
        assert result.drawn_after == []

    def test_seed_reproducible(self) -> None:
        library = [_land() for _ in range(30)] + [_spell(f"S{i}") for i in range(70)]
        r1 = simulate_one(library, rng=random.Random(42))
        r2 = simulate_one(library, rng=random.Random(42))
        assert [c["name"] for c in r1.hand] == [c["name"] for c in r2.hand]

    def test_play_to_extra_draws(self) -> None:
        library = [_land() for _ in range(50)] + [_spell() for _ in range(50)]
        result = simulate_one(library, play_to=3, rng=random.Random(0))
        assert len(result.hand) == DEFAULT_HAND_SIZE
        assert len(result.drawn_after) == 3

    def test_mulligan_with_all_lands_library_keeps_anyway(self) -> None:
        # All-lands library + mulligan_to=5 means every hand has 7 lands and
        # is unkeepable; we should bottom out at max_mulligans and keep.
        library = [_land() for _ in range(60)]
        result = simulate_one(library, mulligan_to=5, rng=random.Random(0))
        assert result.mulligans == 6  # DEFAULT_MAX_MULLIGANS
        assert len(result.hand) == 1
        assert result.cards_bottomed == 6

    def test_mulligan_keeps_first_valid_hand(self) -> None:
        # 50/50 split: many hands will land in [2,5] on the first try.
        library = [_land() for _ in range(50)] + [_spell() for _ in range(50)]
        result = simulate_one(library, mulligan_to=5, rng=random.Random(0))
        summary = hand_summary(result.hand)
        # Either we mulliganed to a smaller hand or we got a 2-5 land 7.
        if result.mulligans == 0:
            assert 2 <= summary["lands"] <= 5


class TestAggregate:
    def test_trial_counts_consistent(self) -> None:
        library = [_land() for _ in range(40)] + [_spell() for _ in range(60)]
        stats = aggregate(library, trials=200, rng=random.Random(1))
        assert stats.trials == 200
        assert sum(stats.land_distribution.values()) == 200
        assert sum(stats.mulligan_distribution.values()) == 200

    def test_avg_lands_in_expected_range(self) -> None:
        # 40/100 lands -> expected lands per 7-card opener ~= 2.8.
        library = [_land() for _ in range(40)] + [_spell() for _ in range(60)]
        stats = aggregate(library, trials=2000, rng=random.Random(7))
        assert 2.4 < stats.avg_lands_in_opener < 3.2

    def test_seed_reproducible(self) -> None:
        library = [_land() for _ in range(40)] + [_spell() for _ in range(60)]
        a = aggregate(library, trials=100, rng=random.Random(99))
        b = aggregate(library, trials=100, rng=random.Random(99))
        assert a.land_distribution == b.land_distribution
        assert a.avg_lands_in_opener == b.avg_lands_in_opener

    def test_library_size_reported(self) -> None:
        library = [_land()] * 30 + [_spell()] * 70
        stats = aggregate(library, trials=10, rng=random.Random(0))
        assert stats.library_size == 100
        assert stats.library_lands == 30
        assert stats.library_spells == 70


# ---------------------------------------------------------------------------
# End-to-end via run()
# ---------------------------------------------------------------------------


@pytest.fixture()
def primed_cache_and_deck(tmp_path: Path) -> Iterator[tuple[Path, Path]]:
    """A small in-memory-style cache + decklist on disk for run() tests."""
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
    # Commander + a handful of lands + spells.
    commander_json = {
        "name": "Test Commander",
        "type_line": "Legendary Creature — Eldrazi",
        "mana_cost": "{5}",
        "cmc": 5.0,
        "color_identity": [],
    }
    plains_json = {
        "name": "Plains",
        "type_line": "Basic Land — Plains",
        "mana_cost": "",
        "cmc": 0.0,
        "produced_mana": ["W"],
    }
    bolt_json = {
        "name": "Bolt",
        "type_line": "Instant",
        "mana_cost": "{R}",
        "cmc": 1.0,
    }
    rows = [
        ("tst", "0", "Test Commander", commander_json),
        ("tst", "1", "Plains", plains_json),
        ("tst", "2", "Bolt", bolt_json),
    ]
    for set_code, cn, name, payload in rows:
        conn.execute(
            "INSERT INTO cards (set_code, collector_number, name, full_json) VALUES (?,?,?,?)",
            (set_code, cn, name, json.dumps(payload)),
        )
    conn.commit()
    conn.close()

    deck_path = tmp_path / "deck.txt"
    deck_lines = ["Commander", "1 Test Commander (tst) 0", "", "Deck"]
    deck_lines.extend(["1 Plains (tst) 1"] * 40)
    deck_lines.extend(["1 Bolt (tst) 2"] * 59)
    deck_path.write_text("\n".join(deck_lines) + "\n", encoding="utf-8")
    yield deck_path, db_path


class TestRun:
    def test_single_hand_json(
        self, primed_cache_and_deck: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        deck_path, cache_path = primed_cache_and_deck
        run(
            decklist=str(deck_path),
            cache=cache_path,
            trials=1,
            seed=0,
            json_flag=True,
        )
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["commander"] == "Test Commander"
        assert payload["library_size"] == 99  # 40 plains + 59 bolts
        assert len(payload["hand"]) == DEFAULT_HAND_SIZE
        assert "summary" in payload

    def test_aggregate_json(
        self, primed_cache_and_deck: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        deck_path, cache_path = primed_cache_and_deck
        run(
            decklist=str(deck_path),
            cache=cache_path,
            trials=50,
            seed=1,
            json_flag=True,
        )
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["trials"] == 50
        assert payload["library_size"] == 99
        assert payload["library_lands"] == 40
        assert sum(payload["land_distribution"].values()) == 50

    def test_seed_makes_single_hand_reproducible(
        self, primed_cache_and_deck: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        deck_path, cache_path = primed_cache_and_deck
        run(decklist=str(deck_path), cache=cache_path, trials=1, seed=123, json_flag=True)
        first = json.loads(capsys.readouterr().out)
        run(decklist=str(deck_path), cache=cache_path, trials=1, seed=123, json_flag=True)
        second = json.loads(capsys.readouterr().out)
        assert [c["name"] for c in first["hand"]] == [c["name"] for c in second["hand"]]

    def test_agent_single_hand_one_line(
        self, primed_cache_and_deck: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        deck_path, cache_path = primed_cache_and_deck
        run(decklist=str(deck_path), cache=cache_path, trials=1, seed=0, agent=True)
        out = capsys.readouterr().out.strip()
        # One line, dense format.
        assert "\n" not in out
        assert out.startswith("hand")
        assert "mulls=0" in out
        assert "lands=" in out
        assert "names=" in out

    def test_agent_aggregate_one_line(
        self, primed_cache_and_deck: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        deck_path, cache_path = primed_cache_and_deck
        run(decklist=str(deck_path), cache=cache_path, trials=200, seed=0, agent=True)
        out = capsys.readouterr().out.strip()
        assert "\n" not in out
        assert out.startswith("agg ")
        assert "trials=200" in out
        assert "keepable=" in out

    def test_multi_hands_agent_one_line_per_hand(
        self, primed_cache_and_deck: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        deck_path, cache_path = primed_cache_and_deck
        run(decklist=str(deck_path), cache=cache_path, hands=4, seed=0, agent=True)
        lines = capsys.readouterr().out.strip().splitlines()
        assert len(lines) == 4
        assert all(line.startswith("hand[") for line in lines)
        # Indices 1..4 present
        assert all(f"[{i}]" in lines[i - 1] for i in range(1, 5))

    def test_multi_hands_json_returns_array(
        self, primed_cache_and_deck: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        deck_path, cache_path = primed_cache_and_deck
        run(decklist=str(deck_path), cache=cache_path, hands=3, seed=0, json_flag=True)
        payload = json.loads(capsys.readouterr().out)
        assert payload["library_size"] == 99
        assert len(payload["hands"]) == 3
        for i, h in enumerate(payload["hands"], 1):
            assert h["index"] == i
            assert len(h["names"]) == DEFAULT_HAND_SIZE
