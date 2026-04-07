"""Tests for manascope.deck — card helpers, parsing, format detection, legality."""

import textwrap
from collections import Counter
from pathlib import Path

import pytest

from manascope.deck import (
    COLOUR_LABELS,
    CREATURE_TYPES,
    CYCLING_RE,
    FORMAT_LEGALITY_FIELD,
    FORMAT_TARGETS,
    WUBRG_ORDER,
    card_cmc_from_cost,
    card_subtypes,
    colour_balance,
    colour_identity,
    detect_format,
    extract_synergy_types,
    has_synergy_type,
    is_artifact,
    is_creature,
    is_land,
    is_legal,
    is_mana_creature,
    is_mana_rock,
    is_within_identity,
    land_speed,
    mana_cost,
    oracle_text,
    parse_decklist,
    pip_colours,
    produced_mana,
    rock_land_equiv,
    sorted_colours,
    type_line,
)

# ── Fixtures: minimal Scryfall-shaped card dicts ─────────────────────────


@pytest.fixture()
def plains() -> dict:
    return {
        "name": "Plains",
        "type_line": "Basic Land — Plains",
        "oracle_text": "({T}: Add {W}.)",
        "produced_mana": ["W"],
        "color_identity": [],
        "cmc": 0,
        "legalities": {
            "commander": "legal",
            "brawl": "legal",
            "standardbrawl": "legal",
        },
    }


@pytest.fixture()
def sol_ring() -> dict:
    return {
        "name": "Sol Ring",
        "type_line": "Artifact",
        "mana_cost": "{1}",
        "oracle_text": "{T}: Add {C}{C}.",
        "produced_mana": ["C"],
        "color_identity": [],
        "cmc": 1.0,
        "legalities": {
            "commander": "legal",
            "brawl": "banned",
            "standardbrawl": "not_legal",
        },
    }


@pytest.fixture()
def kaalia() -> dict:
    return {
        "name": "Kaalia of the Vast",
        "type_line": "Legendary Creature — Human Cleric",
        "mana_cost": "{1}{W}{B}{R}",
        "oracle_text": (
            "Flying\n"
            "Whenever Kaalia of the Vast attacks, you may put an Angel, "
            "Demon, or Dragon creature card from your hand onto the battlefield "
            "tapped and attacking."
        ),
        "color_identity": ["W", "B", "R"],
        "cmc": 4.0,
        "legalities": {
            "commander": "legal",
            "brawl": "legal",
            "standardbrawl": "not_legal",
        },
    }


@pytest.fixture()
def shock_land() -> dict:
    return {
        "name": "Blood Crypt",
        "type_line": "Land — Swamp Mountain",
        "oracle_text": (
            "({T}: Add {B} or {R}.)\n"
            "As Blood Crypt enters, you may pay 2 life. "
            "If you don't, it enters tapped."
        ),
        "produced_mana": ["B", "R"],
        "color_identity": ["B", "R"],
        "cmc": 0,
        "legalities": {
            "commander": "legal",
            "brawl": "legal",
            "standardbrawl": "not_legal",
        },
    }


@pytest.fixture()
def tapped_land() -> dict:
    return {
        "name": "Rakdos Guildgate",
        "type_line": "Land — Gate",
        "oracle_text": "This land enters tapped.\n{T}: Add {B} or {R}.",
        "produced_mana": ["B", "R"],
        "color_identity": ["B", "R"],
        "cmc": 0,
        "legalities": {
            "commander": "legal",
            "brawl": "legal",
            "standardbrawl": "not_legal",
        },
    }


@pytest.fixture()
def fast_land() -> dict:
    return {
        "name": "Blackcleave Cliffs",
        "type_line": "Land",
        "oracle_text": (
            "This land enters tapped unless you control two or fewer other lands.\n"
            "{T}: Add {B} or {R}."
        ),
        "produced_mana": ["B", "R"],
        "color_identity": ["B", "R"],
        "cmc": 0,
        "legalities": {"commander": "legal", "brawl": "legal"},
    }


@pytest.fixture()
def mana_creature() -> dict:
    return {
        "name": "Birds of Paradise",
        "type_line": "Creature — Bird",
        "mana_cost": "{G}",
        "oracle_text": "Flying\n{T}: Add one mana of any color.",
        "produced_mana": ["W", "U", "B", "R", "G"],
        "color_identity": ["G"],
        "cmc": 1.0,
        "legalities": {"commander": "legal", "brawl": "legal"},
    }


@pytest.fixture()
def dfc_card() -> dict:
    """A double-faced card with card_faces."""
    return {
        "name": "Archangel Avacyn // Avacyn, the Purifier",
        "card_faces": [
            {
                "name": "Archangel Avacyn",
                "type_line": "Legendary Creature — Angel",
                "mana_cost": "{3}{W}{W}",
                "oracle_text": "Flash\nFlying, vigilance\nWhen Archangel Avacyn enters, creatures you control gain indestructible until end of turn.",
            },
            {
                "name": "Avacyn, the Purifier",
                "type_line": "Legendary Creature — Angel",
                "mana_cost": "",
                "oracle_text": "Flying\nWhen this creature transforms into Avacyn, the Purifier, it deals 3 damage to each other creature and each opponent.",
            },
        ],
        "type_line": "Legendary Creature — Angel // Legendary Creature — Angel",
        "color_identity": ["R", "W"],
        "cmc": 5.0,
        "legalities": {"commander": "legal", "brawl": "legal"},
    }


# ── mana_cost ────────────────────────────────────────────────────────────


class TestManaCost:
    def test_normal_card(self, kaalia: dict) -> None:
        assert mana_cost(kaalia) == "{1}{W}{B}{R}"

    def test_land_returns_empty(self, plains: dict) -> None:
        assert mana_cost(plains) == ""

    def test_dfc_joins_faces(self, dfc_card: dict) -> None:
        # dfc_card has front face with "{3}{W}{W}" and back with ""
        # Only non-empty costs are joined
        result = mana_cost(dfc_card)
        assert result == "{3}{W}{W}"

    def test_no_mana_cost_key(self) -> None:
        card: dict = {"name": "Some Land", "type_line": "Land"}
        assert mana_cost(card) == ""

    def test_zero_cost_spell(self) -> None:
        card: dict = {"name": "Memnite", "type_line": "Artifact Creature", "mana_cost": "{0}"}
        assert mana_cost(card) == "{0}"

    def test_empty_mana_cost_string(self) -> None:
        # Some cards have mana_cost = "" explicitly
        card: dict = {"name": "Ancestral Vision", "mana_cost": ""}
        assert mana_cost(card) == ""

    def test_dfc_both_faces_have_cost(self) -> None:
        card: dict = {
            "name": "Wear // Tear",
            "card_faces": [
                {"name": "Wear", "mana_cost": "{1}{R}"},
                {"name": "Tear", "mana_cost": "{W}"},
            ],
        }
        assert mana_cost(card) == "{1}{R} // {W}"


# ── oracle_text ──────────────────────────────────────────────────────────


class TestOracleText:
    def test_single_face(self, kaalia: dict) -> None:
        text = oracle_text(kaalia)
        assert "Angel, Demon, or Dragon" in text

    def test_double_face(self, dfc_card: dict) -> None:
        text = oracle_text(dfc_card)
        assert "Flash" in text
        assert "3 damage" in text
        assert " // " in text

    def test_empty(self) -> None:
        assert oracle_text({}) == ""


# ── type_line ────────────────────────────────────────────────────────────


class TestTypeLine:
    def test_single(self, kaalia: dict) -> None:
        assert type_line(kaalia) == "Legendary Creature — Human Cleric"

    def test_dfc(self, dfc_card: dict) -> None:
        tl = type_line(dfc_card)
        assert "Angel" in tl

    def test_empty(self) -> None:
        assert type_line({}) == ""


# ── card_subtypes ────────────────────────────────────────────────────────


class TestCardSubtypes:
    def test_creature(self, kaalia: dict) -> None:
        subs = card_subtypes(kaalia)
        assert subs == {"human", "cleric"}

    def test_land(self, shock_land: dict) -> None:
        subs = card_subtypes(shock_land)
        assert "swamp" in subs
        assert "mountain" in subs

    def test_no_subtypes(self, sol_ring: dict) -> None:
        assert card_subtypes(sol_ring) == set()


# ── is_land / is_artifact / is_creature ──────────────────────────────────


class TestTypeChecks:
    def test_land(self, plains: dict, sol_ring: dict, kaalia: dict) -> None:
        assert is_land(plains) is True
        assert is_land(sol_ring) is False
        assert is_land(kaalia) is False

    def test_artifact(self, sol_ring: dict, kaalia: dict, plains: dict) -> None:
        assert is_artifact(sol_ring) is True
        assert is_artifact(kaalia) is False
        assert is_artifact(plains) is False

    def test_creature(self, kaalia: dict, sol_ring: dict, mana_creature: dict) -> None:
        assert is_creature(kaalia) is True
        assert is_creature(sol_ring) is False
        assert is_creature(mana_creature) is True


# ── land_speed ───────────────────────────────────────────────────────────


class TestLandSpeed:
    def test_basic_untapped(self, plains: dict) -> None:
        assert land_speed(plains) == "untapped"

    def test_shock(self, shock_land: dict) -> None:
        assert land_speed(shock_land) == "shock"

    def test_always_tapped(self, tapped_land: dict) -> None:
        assert land_speed(tapped_land) == "tapped"

    def test_fast_land(self, fast_land: dict) -> None:
        assert land_speed(fast_land) == "conditional"

    def test_slow_land(self) -> None:
        card = {
            "type_line": "Land",
            "oracle_text": (
                "This land enters tapped unless you control two or more other lands.\n"
                "{T}: Add {W} or {U}."
            ),
        }
        assert land_speed(card) == "conditional"

    def test_snarl_land(self) -> None:
        card = {
            "type_line": "Land",
            "oracle_text": (
                "As this land enters, you may reveal a Forest or Plains card "
                "from your hand. If you don't, this land enters tapped.\n"
                "{T}: Add {G} or {W}."
            ),
        }
        assert land_speed(card) == "conditional"

    def test_check_land(self) -> None:
        # Both SNARL_RE and CHECK_RE match this reveal pattern;
        # SNARL_RE is checked first in land_speed() and catches it.
        card = {
            "type_line": "Land",
            "oracle_text": (
                "As this land enters, you may reveal a Swamp or Mountain card "
                "from your hand. If you don't, this land enters tapped.\n"
                "{T}: Add {B} or {R}."
            ),
        }
        assert land_speed(card) == "conditional"

    def test_verge_land(self) -> None:
        card = {
            "type_line": "Land",
            "oracle_text": (
                "{T}: Add {C}.\n"
                "{T}: Add {R} or {W}. Activate only if you control "
                "a Mountain or a Plains."
            ),
        }
        assert land_speed(card) == "conditional"

    def test_filter_land_enters_tapped(self) -> None:
        # FILTER_RE requires hybrid {X/Y} mana symbols; plain {1} does not
        # match, so this falls through to "tapped".
        card = {
            "type_line": "Land",
            "oracle_text": "This land enters tapped.\n{1}, {T}: Add {W}{U}.",
        }
        assert land_speed(card) == "tapped"

    def test_no_oracle_text(self) -> None:
        card = {"type_line": "Basic Land — Forest"}
        assert land_speed(card) == "untapped"


# ── produced_mana ────────────────────────────────────────────────────────


class TestProducedMana:
    def test_from_field(self, plains: dict) -> None:
        assert produced_mana(plains) == {"W"}

    def test_multi_colour(self, shock_land: dict) -> None:
        assert produced_mana(shock_land) == {"B", "R"}

    def test_fallback_to_oracle(self) -> None:
        card = {
            "type_line": "Artifact",
            "oracle_text": "{T}: Add {G}.",
        }
        assert "G" in produced_mana(card)


# ── is_mana_rock / is_mana_creature ─────────────────────────────────────


class TestManaSourceChecks:
    def test_sol_ring_is_rock(self, sol_ring: dict) -> None:
        assert is_mana_rock(sol_ring) is True

    def test_creature_not_rock(self, mana_creature: dict) -> None:
        assert is_mana_rock(mana_creature) is False

    def test_birds_is_mana_creature(self, mana_creature: dict) -> None:
        assert is_mana_creature(mana_creature) is True

    def test_kaalia_not_mana_creature(self, kaalia: dict) -> None:
        assert is_mana_creature(kaalia) is False

    def test_land_not_rock(self, plains: dict) -> None:
        assert is_mana_rock(plains) is False


# ── rock_land_equiv ──────────────────────────────────────────────────────


class TestRockLandEquiv:
    def test_sol_ring(self, sol_ring: dict) -> None:
        assert rock_land_equiv(sol_ring) == 1.0

    def test_mana_creature(self, mana_creature: dict) -> None:
        assert rock_land_equiv(mana_creature) == 0.3

    def test_2cmc_rock(self) -> None:
        signet = {
            "type_line": "Artifact",
            "oracle_text": "{T}: Add {W}{B}.",
            "cmc": 2.0,
        }
        assert rock_land_equiv(signet) == 0.5

    def test_3cmc_rock(self) -> None:
        rock = {
            "type_line": "Artifact",
            "oracle_text": "{T}: Add {R}.",
            "cmc": 3.0,
        }
        assert rock_land_equiv(rock) == 0.3

    def test_expensive_rock(self) -> None:
        rock = {
            "type_line": "Artifact",
            "oracle_text": "{T}: Add {G}.",
            "cmc": 5.0,
        }
        assert rock_land_equiv(rock) == 0.0


# ── pip_colours ──────────────────────────────────────────────────────────


class TestPipColours:
    def test_kaalia_cost(self) -> None:
        pips = pip_colours("{1}{W}{B}{R}", {"W", "B", "R"})
        assert sorted(pips) == ["B", "R", "W"]

    def test_hybrid(self) -> None:
        pips = pip_colours("{W/B}", {"W", "B"})
        assert "W" in pips
        assert "B" in pips

    def test_colourless(self) -> None:
        pips = pip_colours("{3}", {"W", "U", "B", "R", "G"})
        assert pips == []


# ── card_cmc_from_cost ───────────────────────────────────────────────────


class TestCardCmcFromCost:
    def test_kaalia(self) -> None:
        assert card_cmc_from_cost("{1}{W}{B}{R}") == 4

    def test_generic_only(self) -> None:
        assert card_cmc_from_cost("{5}") == 5

    def test_x_spell(self) -> None:
        assert card_cmc_from_cost("{X}{R}{R}") == 2

    def test_empty(self) -> None:
        assert card_cmc_from_cost("") == 0


# ── has_synergy_type ─────────────────────────────────────────────────────


class TestHasSynergyType:
    def test_kaalia_is_human_cleric(self, kaalia: dict) -> None:
        assert has_synergy_type(kaalia, {"human", "cleric"}) is True

    def test_no_match(self, sol_ring: dict) -> None:
        assert has_synergy_type(sol_ring, {"angel", "demon"}) is False

    def test_empty_synergy_set(self, kaalia: dict) -> None:
        assert has_synergy_type(kaalia, set()) is False

    def test_changeling(self) -> None:
        """A card with 'changeling' as a subtype matches any creature type."""
        changeling = {
            "type_line": "Creature — Shapeshifter Changeling",
        }
        assert has_synergy_type(changeling, {"angel"}) is True
        assert has_synergy_type(changeling, {"dragon"}) is True


# ── is_legal ─────────────────────────────────────────────────────────────


class TestIsLegal:
    def test_legal_commander(self, kaalia: dict) -> None:
        assert is_legal(kaalia, "commander") is True

    def test_legal_brawl(self, kaalia: dict) -> None:
        assert is_legal(kaalia, "brawl") is True

    def test_not_legal_standard_brawl(self, kaalia: dict) -> None:
        assert is_legal(kaalia, "standardbrawl") is False

    def test_sol_ring_banned_brawl(self, sol_ring: dict) -> None:
        assert is_legal(sol_ring, "brawl") is False


# ── colour_identity / is_within_identity ─────────────────────────────────


class TestColourIdentity:
    def test_kaalia(self, kaalia: dict) -> None:
        assert colour_identity(kaalia) == {"W", "B", "R"}

    def test_colourless(self, sol_ring: dict) -> None:
        assert colour_identity(sol_ring) == set()

    def test_within(self, sol_ring: dict, kaalia: dict) -> None:
        mardu = {"W", "B", "R"}
        assert is_within_identity(sol_ring, mardu) is True
        assert is_within_identity(kaalia, mardu) is True

    def test_not_within(self, mana_creature: dict) -> None:
        mardu = {"W", "B", "R"}
        assert is_within_identity(mana_creature, mardu) is False  # G not in Mardu


# ── extract_synergy_types ────────────────────────────────────────────────


class TestExtractSynergyTypes:
    def test_kaalia(self, kaalia: dict) -> None:
        types = extract_synergy_types(kaalia)
        assert "angel" in types
        assert "demon" in types
        assert "dragon" in types
        # Commander's own subtypes should also appear
        assert "human" in types or "cleric" in types

    def test_no_synergy(self, sol_ring: dict) -> None:
        types = extract_synergy_types(sol_ring)
        assert types == set()


# ── detect_format ────────────────────────────────────────────────────────


class TestDetectFormat:
    def test_brawl(self) -> None:
        assert detect_format("brawl/kaalia.txt") == "brawl"

    def test_commander(self) -> None:
        assert detect_format("commander/kaalia.txt") == "commander"

    def test_standardbrawl(self) -> None:
        assert detect_format("standardbrawl/maralen.txt") == "standardbrawl"

    def test_fallback(self) -> None:
        assert detect_format("random/deck.txt") == "commander"

    def test_nested_path(self) -> None:
        assert detect_format("some/brawl/deck.txt") == "brawl"


# ── sorted_colours ───────────────────────────────────────────────────────


class TestSortedColours:
    def test_mardu(self) -> None:
        assert sorted_colours({"R", "W", "B"}) == ["W", "B", "R"]

    def test_all(self) -> None:
        assert sorted_colours(set("WUBRG")) == ["W", "U", "B", "R", "G"]

    def test_empty(self) -> None:
        assert sorted_colours(set()) == []


# ── colour_balance ───────────────────────────────────────────────────────


class TestColourBalance:
    def test_balanced(self) -> None:
        sources = Counter({"W": 10, "B": 10})
        pips = Counter({"W": 20, "B": 20})
        result = colour_balance(sources, pips, 20, 40, {"W", "B"})
        assert "W" in result
        assert "B" in result
        # 10/20 = 50% sources, 20/40 = 50% pips → delta 0
        assert result["W"] == pytest.approx((50.0, 50.0, 0.0))


# ── parse_decklist ───────────────────────────────────────────────────────


class TestParseDecklist:
    def test_basic(self, tmp_path: Path) -> None:
        deck = tmp_path / "test.txt"
        deck.write_text(
            textwrap.dedent("""\
                1 Kaalia of the Vast (MH3) 290
                2 Plains (ONE) 267
                1 Sol Ring (C21) 263
            """),
            encoding="utf-8",
        )
        entries = parse_decklist(str(deck))
        assert len(entries) == 3
        assert entries[0][0] == 1  # qty
        assert entries[0][1].name == "Kaalia of the Vast"
        assert entries[0][1].set_code == "MH3"
        assert entries[0][1].collector_number == "290"
        assert entries[1][0] == 2  # Plains x2

    def test_blank_lines_skipped(self, tmp_path: Path) -> None:
        deck = tmp_path / "test.txt"
        deck.write_text(
            "1 Sol Ring (C21) 263\n\n1 Plains (ONE) 267\n",
            encoding="utf-8",
        )
        entries = parse_decklist(str(deck))
        assert len(entries) == 2

    def test_arena_headers_commander_first(self, tmp_path: Path) -> None:
        """Cards under a Commander header appear first in the result list."""
        deck = tmp_path / "test.txt"
        deck.write_text(
            textwrap.dedent("""\
                Commander
                1 Kaalia of the Vast (MH3) 290

                Deck
                1 Sol Ring (C21) 263
                2 Plains (ONE) 267
            """),
            encoding="utf-8",
        )
        entries = parse_decklist(str(deck))
        assert len(entries) == 3
        assert entries[0][1].name == "Kaalia of the Vast"
        assert entries[1][1].name == "Sol Ring"
        assert entries[2][0] == 2

    def test_arena_headers_no_warnings(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Arena section headers should not produce stderr warnings."""
        deck = tmp_path / "test.txt"
        deck.write_text(
            textwrap.dedent("""\
                Commander
                1 Kaalia of the Vast (MH3) 290

                Deck
                1 Sol Ring (C21) 263
            """),
            encoding="utf-8",
        )
        parse_decklist(str(deck))
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_arena_headers_case_insensitive(self, tmp_path: Path) -> None:
        """Section headers should be recognised regardless of case."""
        deck = tmp_path / "test.txt"
        deck.write_text(
            textwrap.dedent("""\
                COMMANDER
                1 Kaalia of the Vast (MH3) 290

                deck
                1 Sol Ring (C21) 263
            """),
            encoding="utf-8",
        )
        entries = parse_decklist(str(deck))
        assert len(entries) == 2
        assert entries[0][1].name == "Kaalia of the Vast"

    def test_no_headers_first_line_is_commander(self, tmp_path: Path) -> None:
        """Without headers, line 1 remains the commander (backward compat)."""
        deck = tmp_path / "test.txt"
        deck.write_text(
            textwrap.dedent("""\
                1 Kaalia of the Vast (MH3) 290
                1 Sol Ring (C21) 263
            """),
            encoding="utf-8",
        )
        entries = parse_decklist(str(deck))
        assert entries[0][1].name == "Kaalia of the Vast"

    def test_sideboard_section_parsed(self, tmp_path: Path) -> None:
        """Sideboard cards are parsed (placed after commander + deck)."""
        deck = tmp_path / "test.txt"
        deck.write_text(
            textwrap.dedent("""\
                Commander
                1 Kaalia of the Vast (MH3) 290

                Deck
                1 Sol Ring (C21) 263

                Sideboard
                1 Plains (ONE) 267
            """),
            encoding="utf-8",
        )
        entries = parse_decklist(str(deck))
        assert len(entries) == 3
        assert entries[0][1].name == "Kaalia of the Vast"
        assert entries[1][1].name == "Sol Ring"
        assert entries[2][1].name == "Plains"


# ── Constants sanity ─────────────────────────────────────────────────────


class TestConstants:
    def test_colour_labels_complete(self) -> None:
        for c in WUBRG_ORDER:
            assert c in COLOUR_LABELS

    def test_format_targets_keys(self) -> None:
        for fmt in ("commander", "brawl", "standardbrawl"):
            assert fmt in FORMAT_TARGETS
            low, high, label = FORMAT_TARGETS[fmt]
            assert low < high
            assert isinstance(label, str)

    def test_format_legality_field_keys(self) -> None:
        for fmt in ("commander", "brawl", "standardbrawl"):
            assert fmt in FORMAT_LEGALITY_FIELD

    def test_creature_types_not_empty(self) -> None:
        assert len(CREATURE_TYPES) > 200
        assert "angel" in CREATURE_TYPES
        assert "demon" in CREATURE_TYPES
        assert "dragon" in CREATURE_TYPES


# ── Cycling detection ────────────────────────────────────────────────────


class TestCyclingDetection:
    def test_matches_cycling_keyword(self) -> None:
        assert CYCLING_RE.search("Cycling {2}") is not None

    def test_does_not_match_recycling(self) -> None:
        assert CYCLING_RE.search("recycling") is None
