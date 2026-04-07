"""Tests for manascope.display — card display formatting helpers."""

import pytest

from manascope.display import (
    _card_to_json,
    _display_card,
    _land_type_note,
    _mana_cost_display,
    _notable_creature_types,
    _produced_mana_display,
    _rock_equiv_label,
    _speed_label,
)

# ── Fixtures: minimal Scryfall-shaped card dicts ─────────────────────────


@pytest.fixture()
def angel() -> dict:
    return {
        "name": "Serra Angel",
        "type_line": "Creature — Angel",
        "mana_cost": "{3}{W}{W}",
        "cmc": 5,
        "colors": ["W"],
        "color_identity": ["W"],
        "oracle_text": "Flying\nVigilance",
        "rarity": "rare",
        "set": "dmr",
        "collector_number": "32",
        "power": "4",
        "toughness": "4",
    }


@pytest.fixture()
def dragon() -> dict:
    return {
        "name": "Shivan Dragon",
        "type_line": "Creature — Dragon",
        "mana_cost": "{4}{R}{R}",
        "cmc": 6,
        "colors": ["R"],
        "color_identity": ["R"],
        "oracle_text": "Flying\n{R}: Shivan Dragon gets +1/+0 until end of turn.",
        "rarity": "rare",
        "set": "m20",
        "collector_number": "335",
        "power": "5",
        "toughness": "5",
    }


@pytest.fixture()
def changeling() -> dict:
    return {
        "name": "Changeling Outcast",
        "type_line": "Creature — Shapeshifter Changeling",
        "mana_cost": "{B}",
        "cmc": 1,
        "colors": ["B"],
        "color_identity": ["B"],
        "oracle_text": "Changeling\nChangeling Outcast can't block and can't be blocked.",
        "rarity": "common",
        "set": "mh1",
        "collector_number": "82",
        "power": "1",
        "toughness": "1",
    }


@pytest.fixture()
def shock_land() -> dict:
    return {
        "name": "Sacred Foundry",
        "type_line": "Land — Mountain Plains",
        "mana_cost": None,
        "cmc": 0,
        "colors": [],
        "color_identity": ["R", "W"],
        "oracle_text": (
            "({T}: Add {R} or {W}.)\n"
            "As Sacred Foundry enters, you may pay 2 life. "
            "If you don't, it enters tapped."
        ),
        "produced_mana": ["R", "W"],
        "rarity": "rare",
        "set": "rna",
        "collector_number": "254",
    }


@pytest.fixture()
def tapped_land() -> dict:
    return {
        "name": "Boros Guildgate",
        "type_line": "Land — Gate",
        "mana_cost": None,
        "cmc": 0,
        "colors": [],
        "color_identity": ["R", "W"],
        "oracle_text": "This land enters tapped.\n{T}: Add {R} or {W}.",
        "produced_mana": ["R", "W"],
        "rarity": "common",
        "set": "rna",
        "collector_number": "243",
    }


@pytest.fixture()
def basic_land() -> dict:
    return {
        "name": "Plains",
        "type_line": "Basic Land — Plains",
        "mana_cost": None,
        "cmc": 0,
        "colors": [],
        "color_identity": ["W"],
        "oracle_text": "({T}: Add {W}.)",
        "produced_mana": ["W"],
        "rarity": "common",
        "set": "m21",
        "collector_number": "260",
    }


@pytest.fixture()
def utility_land() -> dict:
    """A land with no basic subtypes."""
    return {
        "name": "Command Tower",
        "type_line": "Land",
        "mana_cost": None,
        "cmc": 0,
        "colors": [],
        "color_identity": [],
        "oracle_text": "{T}: Add one mana of any color in your commander's color identity.",
        "produced_mana": ["W", "U", "B", "R", "G"],
        "rarity": "common",
        "set": "cmr",
        "collector_number": "350",
    }


@pytest.fixture()
def sol_ring() -> dict:
    return {
        "name": "Sol Ring",
        "type_line": "Artifact",
        "mana_cost": "{1}",
        "cmc": 1,
        "colors": [],
        "color_identity": [],
        "oracle_text": "{T}: Add {C}{C}.",
        "rarity": "uncommon",
        "set": "cmr",
        "collector_number": "472",
    }


@pytest.fixture()
def signet() -> dict:
    return {
        "name": "Boros Signet",
        "type_line": "Artifact",
        "mana_cost": "{2}",
        "cmc": 2,
        "colors": [],
        "color_identity": ["R", "W"],
        "oracle_text": "{1}, {T}: Add {R}{W}.",
        "rarity": "uncommon",
        "set": "cmr",
        "collector_number": "459",
    }


@pytest.fixture()
def mana_creature() -> dict:
    return {
        "name": "Llanowar Elves",
        "type_line": "Creature — Elf Druid",
        "mana_cost": "{G}",
        "cmc": 1,
        "colors": ["G"],
        "color_identity": ["G"],
        "oracle_text": "{T}: Add {G}.",
        "rarity": "common",
        "set": "m19",
        "collector_number": "314",
        "power": "1",
        "toughness": "1",
    }


@pytest.fixture()
def dfc_card() -> dict:
    """A double-faced card with card_faces and no top-level mana_cost."""
    return {
        "name": "Delver of Secrets // Insectile Aberration",
        "type_line": "Creature — Human Wizard // Creature — Human Insect",
        "cmc": 1,
        "colors": ["U"],
        "color_identity": ["U"],
        "rarity": "common",
        "set": "mid",
        "collector_number": "47",
        "card_faces": [
            {
                "name": "Delver of Secrets",
                "type_line": "Creature — Human Wizard",
                "mana_cost": "{U}",
                "oracle_text": (
                    "At the beginning of your upkeep, look at the top card of your "
                    "library. You may reveal that card. If an instant or sorcery card "
                    "is revealed this way, transform Delver of Secrets."
                ),
                "power": "1",
                "toughness": "1",
            },
            {
                "name": "Insectile Aberration",
                "type_line": "Creature — Human Insect",
                "mana_cost": "",
                "oracle_text": "Flying",
                "power": "3",
                "toughness": "2",
            },
        ],
        "power": "1",
        "toughness": "1",
    }


@pytest.fixture()
def sorcery() -> dict:
    return {
        "name": "Lightning Bolt",
        "type_line": "Instant",
        "mana_cost": "{R}",
        "cmc": 1,
        "colors": ["R"],
        "color_identity": ["R"],
        "oracle_text": "Lightning Bolt deals 3 damage to any target.",
        "rarity": "uncommon",
        "set": "2xm",
        "collector_number": "141",
    }


@pytest.fixture()
def conditional_land() -> dict:
    return {
        "name": "Inspiring Vantage",
        "type_line": "Land",
        "mana_cost": None,
        "cmc": 0,
        "colors": [],
        "color_identity": ["R", "W"],
        "oracle_text": (
            "This land enters tapped unless you control two or fewer other lands.\n"
            "{T}: Add {R} or {W}."
        ),
        "produced_mana": ["R", "W"],
        "rarity": "rare",
        "set": "kld",
        "collector_number": "246",
    }


@pytest.fixture()
def heavy_rock() -> dict:
    """A 4+ CMC mana rock."""
    return {
        "name": "Thran Dynamo",
        "type_line": "Artifact",
        "mana_cost": "{4}",
        "cmc": 4,
        "colors": [],
        "color_identity": [],
        "oracle_text": "{T}: Add {C}{C}{C}.",
        "rarity": "uncommon",
        "set": "ima",
        "collector_number": "228",
    }


@pytest.fixture()
def three_cmc_rock() -> dict:
    return {
        "name": "Chromatic Lantern",
        "type_line": "Artifact",
        "mana_cost": "{3}",
        "cmc": 3,
        "colors": [],
        "color_identity": [],
        "oracle_text": (
            'Lands you control have "{T}: Add one mana of any color."\n'
            "{T}: Add one mana of any color."
        ),
        "rarity": "rare",
        "set": "grn",
        "collector_number": "233",
        "produced_mana": ["W", "U", "B", "R", "G"],
    }


@pytest.fixture()
def card_with_legalities(angel) -> dict:
    angel["legalities"] = {
        "commander": "legal",
        "brawl": "legal",
        "standardbrawl": "not_legal",
        "historic": "legal",
        "timeless": "legal",
        "modern": "legal",  # filtered out
        "legacy": "legal",  # filtered out
    }
    return angel


@pytest.fixture()
def planeswalker() -> dict:
    return {
        "name": "Jace, the Mind Sculptor",
        "type_line": "Legendary Planeswalker — Jace",
        "mana_cost": "{2}{U}{U}",
        "cmc": 4,
        "colors": ["U"],
        "color_identity": ["U"],
        "oracle_text": (
            "+2: Look at the top card of target player's library.\n"
            "0: Draw three cards, then put two cards from your hand on top.\n"
            "-1: Return target creature to its owner's hand.\n"
            "-12: Exile all cards from target player's library, then that player "
            "shuffles their hand into their library."
        ),
        "rarity": "mythic",
        "set": "2xm",
        "collector_number": "56",
        "loyalty": "3",
    }


@pytest.fixture()
def creature_no_notable() -> dict:
    """A creature with no notable types."""
    return {
        "name": "Grizzly Bears",
        "type_line": "Creature — Bear",
        "mana_cost": "{1}{G}",
        "cmc": 2,
        "colors": ["G"],
        "color_identity": ["G"],
        "oracle_text": "",
        "rarity": "common",
        "set": "m12",
        "collector_number": "177",
        "power": "2",
        "toughness": "2",
    }


# ── Tests: _card_to_json ─────────────────────────────────────────────────


class TestCardToJson:
    def test_simple_creature(self, angel: dict) -> None:
        result = _card_to_json(angel)
        assert result["name"] == "Serra Angel"
        assert result["type_line"] == "Creature — Angel"
        assert result["mana_cost"] == "{3}{W}{W}"
        assert result["cmc"] == 5
        assert result["colors"] == ["W"]
        assert result["color_identity"] == ["W"]
        assert result["oracle_text"] == "Flying\nVigilance"
        assert result["rarity"] == "rare"
        assert result["set"] == "DMR"
        assert result["collector_number"] == "32"
        assert result["power"] == "4"
        assert result["toughness"] == "4"
        assert "angel" in result["subtypes"]
        assert "notable_types" in result
        assert "Angel" in result["notable_types"]
        # Creatures without mana production should not have land fields
        assert "produced_mana" not in result
        assert "land_speed" not in result
        # Not a mana rock or mana creature
        assert "land_equiv" not in result

    def test_land_card(self, shock_land: dict) -> None:
        result = _card_to_json(shock_land)
        assert result["name"] == "Sacred Foundry"
        assert "Land" in result["type_line"]
        assert "produced_mana" in result
        assert sorted(result["produced_mana"]) == ["R", "W"]
        assert result["land_speed"] == "shock"
        # Lands should not have notable_types
        assert "notable_types" not in result

    def test_mana_rock(self, signet: dict) -> None:
        result = _card_to_json(signet)
        assert result["name"] == "Boros Signet"
        assert "land_equiv" in result
        assert isinstance(result["land_equiv"], float)
        assert result["land_equiv"] == 0.5

    def test_notable_creature_types(self, dragon: dict) -> None:
        result = _card_to_json(dragon)
        assert "notable_types" in result
        assert "Dragon" in result["notable_types"]

    def test_dfc_card(self, dfc_card: dict) -> None:
        result = _card_to_json(dfc_card)
        assert result["name"] == "Delver of Secrets // Insectile Aberration"
        assert result["cmc"] == 1
        # mana_cost should come from DFC face join
        assert "{U}" in result["mana_cost"]
        # oracle text should be joined from faces
        assert "transform Delver of Secrets" in result["oracle_text"]
        assert "Flying" in result["oracle_text"]

    def test_card_with_legalities(self, card_with_legalities: dict) -> None:
        result = _card_to_json(card_with_legalities)
        assert "legalities" in result
        legs = result["legalities"]
        # Only the filtered formats should be present
        assert "commander" in legs
        assert "brawl" in legs
        assert "standardbrawl" in legs
        assert "historic" in legs
        assert "timeless" in legs
        # These should be filtered out
        assert "modern" not in legs
        assert "legacy" not in legs

    def test_no_notable_creature_types(self, creature_no_notable: dict) -> None:
        result = _card_to_json(creature_no_notable)
        assert "notable_types" not in result

    def test_planeswalker_loyalty(self, planeswalker: dict) -> None:
        result = _card_to_json(planeswalker)
        assert result["loyalty"] == "3"
        assert "power" not in result
        assert "toughness" not in result

    def test_mana_creature_has_land_equiv(self, mana_creature: dict) -> None:
        result = _card_to_json(mana_creature)
        assert "land_equiv" in result
        assert result["land_equiv"] == 0.3

    def test_sol_ring_high_equiv(self, sol_ring: dict) -> None:
        result = _card_to_json(sol_ring)
        assert "land_equiv" in result
        assert result["land_equiv"] == 1.0

    def test_basic_land(self, basic_land: dict) -> None:
        result = _card_to_json(basic_land)
        assert result["produced_mana"] == ["W"]
        assert result["land_speed"] == "untapped"
        assert "plains" in result["subtypes"]


# ── Tests: _mana_cost_display ────────────────────────────────────────────


class TestManaCostDisplay:
    def test_normal_card(self, angel: dict) -> None:
        assert _mana_cost_display(angel) == "{3}{W}{W}"

    def test_dfc_with_costs(self, dfc_card: dict) -> None:
        result = _mana_cost_display(dfc_card)
        # Front face has {U}, back face has empty string (filtered out)
        assert result == "{U}"

    def test_land_no_cost(self, basic_land: dict) -> None:
        # mana_cost is None → falls through to card_faces check, none found
        result = _mana_cost_display(basic_land)
        assert result == "(none)"

    def test_empty_mana_cost_string(self) -> None:
        card = {"mana_cost": ""}
        assert _mana_cost_display(card) == "(none)"

    def test_dfc_both_faces_have_cost(self) -> None:
        card = {
            "card_faces": [
                {"mana_cost": "{1}{R}"},
                {"mana_cost": "{3}{R}{R}"},
            ]
        }
        assert _mana_cost_display(card) == "{1}{R} // {3}{R}{R}"


# ── Tests: _produced_mana_display ────────────────────────────────────────


class TestProducedManaDisplay:
    def test_land_produces_mana(self, shock_land: dict) -> None:
        result = _produced_mana_display(shock_land)
        # Should produce formatted symbols in sorted order
        assert "{R}" in result
        assert "{W}" in result

    def test_nonland_no_produced_mana(self, angel: dict) -> None:
        result = _produced_mana_display(angel)
        assert result == "-"

    def test_basic_land(self, basic_land: dict) -> None:
        result = _produced_mana_display(basic_land)
        assert result == "{W}"

    def test_five_color_land(self, utility_land: dict) -> None:
        result = _produced_mana_display(utility_land)
        for color in ["B", "G", "R", "U", "W"]:
            assert "{" + color + "}" in result


# ── Tests: _land_type_note ───────────────────────────────────────────────


class TestLandTypeNote:
    def test_dual_land_with_basic_types(self, shock_land: dict) -> None:
        result = _land_type_note(shock_land)
        assert "Mountain" in result
        assert "Plains" in result

    def test_land_without_basic_types(self, utility_land: dict) -> None:
        result = _land_type_note(utility_land)
        assert result == ""

    def test_non_land(self, angel: dict) -> None:
        result = _land_type_note(angel)
        assert result == ""

    def test_basic_land(self, basic_land: dict) -> None:
        result = _land_type_note(basic_land)
        assert "Plains" in result

    def test_gate_no_basic_types(self, tapped_land: dict) -> None:
        # Gate is not a basic land type
        result = _land_type_note(tapped_land)
        assert result == ""


# ── Tests: _speed_label ─────────────────────────────────────────────────


class TestSpeedLabel:
    def test_untapped(self, basic_land: dict) -> None:
        result = _speed_label(basic_land)
        assert result == "untapped"

    def test_shock(self, shock_land: dict) -> None:
        result = _speed_label(shock_land)
        assert "shock" in result
        assert "pay 2 life" in result

    def test_tapped(self, tapped_land: dict) -> None:
        result = _speed_label(tapped_land)
        assert "always tapped" in result

    def test_conditional(self, conditional_land: dict) -> None:
        result = _speed_label(conditional_land)
        assert result == "conditional"

    def test_utility_land_untapped(self, utility_land: dict) -> None:
        result = _speed_label(utility_land)
        assert result == "untapped"


# ── Tests: _rock_equiv_label ────────────────────────────────────────────


class TestRockEquivLabel:
    def test_two_cmc_rock(self, signet: dict) -> None:
        result = _rock_equiv_label(signet)
        assert "0.5" in result
        assert "2 CMC" in result

    def test_mana_creature(self, mana_creature: dict) -> None:
        result = _rock_equiv_label(mana_creature)
        assert "0.3" in result
        assert "mana creature" in result
        assert "fragile" in result

    def test_land_returns_empty(self, shock_land: dict) -> None:
        result = _rock_equiv_label(shock_land)
        assert result == ""

    def test_non_rock_non_creature_returns_empty(self, sorcery: dict) -> None:
        result = _rock_equiv_label(sorcery)
        assert result == ""

    def test_sol_ring_strong(self, sol_ring: dict) -> None:
        result = _rock_equiv_label(sol_ring)
        assert "1.0" in result
        assert "strong land substitute" in result

    def test_three_cmc_rock(self, three_cmc_rock: dict) -> None:
        result = _rock_equiv_label(three_cmc_rock)
        assert "0.3" in result
        assert "3 CMC" in result

    def test_heavy_rock_no_credit(self, heavy_rock: dict) -> None:
        result = _rock_equiv_label(heavy_rock)
        assert "0.0" in result
        assert "4+ CMC" in result


# ── Tests: _notable_creature_types ──────────────────────────────────────


class TestNotableCreatureTypes:
    def test_dragon(self, dragon: dict) -> None:
        result = _notable_creature_types(dragon)
        assert "Dragon" in result

    def test_angel(self, angel: dict) -> None:
        result = _notable_creature_types(angel)
        assert "Angel" in result

    def test_changeling(self, changeling: dict) -> None:
        result = _notable_creature_types(changeling)
        assert "Changeling" in result
        assert "every creature type" in result

    def test_non_creature(self, sorcery: dict) -> None:
        result = _notable_creature_types(sorcery)
        assert result == ""

    def test_creature_no_notable_types(self, creature_no_notable: dict) -> None:
        result = _notable_creature_types(creature_no_notable)
        assert result == ""

    def test_land_not_creature(self, basic_land: dict) -> None:
        result = _notable_creature_types(basic_land)
        assert result == ""


# ── Tests: _display_card (capsys integration) ───────────────────────────


class TestDisplayCard:
    def test_creature_output(self, capsys: pytest.CaptureFixture[str], angel: dict) -> None:
        _display_card(angel)
        out = capsys.readouterr().out
        assert "Serra Angel" in out
        assert "Creature — Angel" in out
        assert "{3}{W}{W}" in out
        assert "Flying" in out
        assert "Vigilance" in out
        assert "4 / 4" in out
        assert "Angel" in out  # notable type or subtype

    def test_land_output_sections(
        self, capsys: pytest.CaptureFixture[str], shock_land: dict
    ) -> None:
        _display_card(shock_land)
        out = capsys.readouterr().out
        assert "Sacred Foundry" in out
        assert "Produces" in out
        assert "Basic types" in out
        assert "Entry speed" in out
        assert "Mountain" in out
        assert "Plains" in out
        assert "Shock land" in out
        assert "Deck interaction notes" in out

    def test_tapped_land_notes(self, capsys: pytest.CaptureFixture[str], tapped_land: dict) -> None:
        _display_card(tapped_land)
        out = capsys.readouterr().out
        assert "always tapped" in out
        assert "costs you a tempo" in out

    def test_conditional_land_notes(
        self, capsys: pytest.CaptureFixture[str], conditional_land: dict
    ) -> None:
        _display_card(conditional_land)
        out = capsys.readouterr().out
        assert "conditional" in out.lower()

    def test_untapped_land_notes(
        self, capsys: pytest.CaptureFixture[str], basic_land: dict
    ) -> None:
        _display_card(basic_land)
        out = capsys.readouterr().out
        assert "Reliably enters untapped" in out

    def test_land_no_basic_types_note(
        self, capsys: pytest.CaptureFixture[str], utility_land: dict
    ) -> None:
        _display_card(utility_land)
        out = capsys.readouterr().out
        assert "No basic land type" in out
        assert "cannot be found by fetch lands" in out

    def test_mana_rock_output(self, capsys: pytest.CaptureFixture[str], sol_ring: dict) -> None:
        _display_card(sol_ring)
        out = capsys.readouterr().out
        assert "Sol Ring" in out
        assert "Land equivalent" in out

    def test_planeswalker_loyalty(
        self, capsys: pytest.CaptureFixture[str], planeswalker: dict
    ) -> None:
        _display_card(planeswalker)
        out = capsys.readouterr().out
        assert "Jace, the Mind Sculptor" in out
        assert "Loyalty" in out

    def test_brief_mode_hides_rarity_and_price(
        self, capsys: pytest.CaptureFixture[str], angel: dict
    ) -> None:
        _display_card(angel, brief=True)
        out = capsys.readouterr().out
        assert "Serra Angel" in out
        # brief=True should NOT show rarity/price line
        assert "Rarity" not in out
        assert "Price" not in out

    def test_full_mode_shows_rarity_and_price(
        self, capsys: pytest.CaptureFixture[str], angel: dict
    ) -> None:
        _display_card(angel, brief=False)
        out = capsys.readouterr().out
        assert "Rarity" in out

    def test_dfc_output(self, capsys: pytest.CaptureFixture[str], dfc_card: dict) -> None:
        _display_card(dfc_card)
        out = capsys.readouterr().out
        assert "Delver of Secrets" in out

    def test_separator_present(self, capsys: pytest.CaptureFixture[str], angel: dict) -> None:
        _display_card(angel)
        out = capsys.readouterr().out
        sep = "-" * 72
        assert sep in out

    def test_mana_creature_output(
        self, capsys: pytest.CaptureFixture[str], mana_creature: dict
    ) -> None:
        _display_card(mana_creature)
        out = capsys.readouterr().out
        assert "Llanowar Elves" in out
        assert "Land equivalent" in out
        assert "mana creature" in out
