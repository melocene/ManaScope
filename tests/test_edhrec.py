"""Tests for manascope.edhrec — data models, slugification, and extraction helpers."""

from datetime import UTC, datetime, timedelta

import pytest

from manascope.edhrec import (
    Combo,
    SynergyCard,
    TagInfo,
    TypeDistribution,
    _extract_cardlist,
    _is_stale,
    all_recommended_cards,
    average_deck_price,
    cards_by_category,
    combos,
    combos_url,
    game_changers,
    high_synergy_cards,
    mana_curve,
    new_cards,
    num_decks,
    open_cache,
    slugify,
    tags,
    top_cards,
    type_distribution,
)

# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture()
def sample_type_dist() -> TypeDistribution:
    """A realistic 100-card Commander type distribution."""
    return TypeDistribution(
        creature=28,
        instant=9,
        sorcery=8,
        artifact=10,
        enchantment=7,
        battle=0,
        planeswalker=2,
        land=36,
        total=100,
    )


@pytest.fixture()
def zero_type_dist() -> TypeDistribution:
    """A type distribution with total=0."""
    return TypeDistribution(
        creature=0,
        instant=0,
        sorcery=0,
        artifact=0,
        enchantment=0,
        battle=0,
        planeswalker=0,
        land=0,
        total=0,
    )


@pytest.fixture()
def sample_synergy_card() -> SynergyCard:
    return SynergyCard(
        name="Smothering Tithe",
        synergy=0.61,
        inclusion=8500,
        potential_decks=10000,
        category="highsynergycards",
    )


@pytest.fixture()
def edhrec_data() -> dict:
    """Minimal but realistic EDHREC JSON structure for extraction tests."""
    return {
        "header": "Kaalia of the Vast (Commander)",
        "num_decks_avg": 12345,
        "avg_price": 450.75,
        "creature": 28,
        "instant": 9,
        "sorcery": 8,
        "artifact": 10,
        "enchantment": 7,
        "battle": 0,
        "planeswalker": 2,
        "land": 36,
        "total_card_count": 100,
        "panels": {
            "mana_curve": {
                "1": 10,
                "2": 19,
                "3": 15,
                "4": 12,
                "5": 5,
                "6": 2,
                "7": 1,
            },
            "combocounts": [
                {
                    "value": "Master of Cruelties + Kaalia",
                    "href": "/combos/wb/master-of-cruelties-kaalia",
                },
                {
                    "value": "Razaketh + Reanimate",
                    "href": "/combos/wb/razaketh-reanimate",
                },
                {
                    "value": "See More...",
                    "href": "/combos/wbr/kaalia-of-the-vast",
                },
            ],
            "taglinks": [
                {"value": "Angels", "slug": "angels", "count": 3200},
                {"value": "Demons", "slug": "demons", "count": 1800},
                {"value": "Reanimator", "slug": "reanimator", "count": 950},
                {"value": "Dragons", "slug": "dragons", "count": 2400},
            ],
        },
        "container": {
            "json_dict": {
                "cardlists": [
                    {
                        "tag": "highsynergycards",
                        "cardviews": [
                            {
                                "name": "Aurelia, the Warleader",
                                "synergy": 0.72,
                                "num_decks": 8000,
                                "potential_decks": 10000,
                            },
                            {
                                "name": "Master of Cruelties",
                                "synergy": 0.65,
                                "num_decks": 7500,
                                "potential_decks": 10000,
                            },
                        ],
                    },
                    {
                        "tag": "topcards",
                        "cardviews": [
                            {
                                "name": "Sol Ring",
                                "synergy": 0.01,
                                "num_decks": 9800,
                                "potential_decks": 10000,
                            },
                            {
                                "name": "Smothering Tithe",
                                "synergy": 0.15,
                                "num_decks": 8500,
                                "potential_decks": 10000,
                            },
                        ],
                    },
                    {
                        "tag": "gamechangers",
                        "cardviews": [
                            {
                                "name": "Avacyn, Angel of Hope",
                                "synergy": 0.45,
                                "num_decks": 6000,
                                "potential_decks": 10000,
                            },
                        ],
                    },
                    {
                        "tag": "newcards",
                        "cardviews": [
                            {
                                "name": "Some New Angel",
                                "synergy": 0.30,
                                "num_decks": 3000,
                                "potential_decks": 10000,
                            },
                        ],
                    },
                    {
                        "tag": "creatures",
                        "cardviews": [
                            {
                                "name": "Aurelia, the Warleader",
                                "synergy": 0.70,
                                "num_decks": 8000,
                                "potential_decks": 10000,
                            },
                            {
                                "name": "Rune-Scarred Demon",
                                "synergy": 0.40,
                                "num_decks": 5000,
                                "potential_decks": 10000,
                            },
                        ],
                    },
                    {
                        "tag": "lands",
                        "cardviews": [
                            {
                                "name": "Command Tower",
                                "synergy": 0.02,
                                "num_decks": 9900,
                                "potential_decks": 10000,
                            },
                        ],
                    },
                ],
            }
        },
        "similar": [
            {"name": "Edgar Markov", "sanitized": "edgar-markov"},
        ],
    }


# ── TypeDistribution ────────────────────────────────────────────────────


class TestTypeDistribution:
    def test_as_percentages(self, sample_type_dist: TypeDistribution) -> None:
        pcts = sample_type_dist.as_percentages()
        assert pcts["creature"] == 28.0
        assert pcts["land"] == 36.0
        assert pcts["instant"] == 9.0
        assert pcts["battle"] == 0.0
        assert "total" not in pcts
        assert sum(pcts.values()) == pytest.approx(100.0)

    def test_as_percentages_zero_total(self, zero_type_dist: TypeDistribution) -> None:
        pcts = zero_type_dist.as_percentages()
        assert all(v == 0.0 for v in pcts.values())
        assert "total" not in pcts

    def test_as_percentages_nonstandard_total(self) -> None:
        td = TypeDistribution(
            creature=10,
            instant=5,
            sorcery=5,
            artifact=0,
            enchantment=0,
            battle=0,
            planeswalker=0,
            land=20,
            total=40,
        )
        pcts = td.as_percentages()
        assert pcts["creature"] == 25.0
        assert pcts["land"] == 50.0

    def test_scaled_to_60(self, sample_type_dist: TypeDistribution) -> None:
        scaled = sample_type_dist.scaled_to(60)
        assert sum(scaled.values()) == 60
        assert "total" not in scaled
        # The relative ordering should be preserved
        assert scaled["land"] > scaled["creature"] > scaled["instant"]
        assert all(isinstance(v, int) for v in scaled.values())

    def test_scaled_to_100_matches_original(self, sample_type_dist: TypeDistribution) -> None:
        scaled = sample_type_dist.scaled_to(100)
        assert sum(scaled.values()) == 100
        assert scaled["creature"] == 28
        assert scaled["land"] == 36

    def test_scaled_to_zero_total(self, zero_type_dist: TypeDistribution) -> None:
        scaled = zero_type_dist.scaled_to(60)
        assert all(v == 0 for v in scaled.values())
        assert "total" not in scaled

    def test_scaled_to_small_deck(self, sample_type_dist: TypeDistribution) -> None:
        scaled = sample_type_dist.scaled_to(10)
        assert sum(scaled.values()) == 10


# ── SynergyCard ─────────────────────────────────────────────────────────


class TestSynergyCard:
    def test_inclusion_pct(self, sample_synergy_card: SynergyCard) -> None:
        assert sample_synergy_card.inclusion_pct == 85.0

    def test_inclusion_pct_zero_decks(self) -> None:
        card = SynergyCard(
            name="Ghost Card",
            synergy=0.5,
            inclusion=0,
            potential_decks=0,
            category="topcards",
        )
        assert card.inclusion_pct == 0.0

    def test_inclusion_pct_partial(self) -> None:
        card = SynergyCard(
            name="Niche Combo Piece",
            synergy=0.8,
            inclusion=333,
            potential_decks=1000,
            category="highsynergycards",
        )
        assert card.inclusion_pct == 33.3

    def test_synergy_pct(self, sample_synergy_card: SynergyCard) -> None:
        assert sample_synergy_card.synergy_pct == 61.0

    def test_synergy_pct_negative(self) -> None:
        card = SynergyCard(
            name="Bad Card",
            synergy=-0.15,
            inclusion=100,
            potential_decks=10000,
            category="topcards",
        )
        assert card.synergy_pct == -15.0

    def test_synergy_pct_zero(self) -> None:
        card = SynergyCard(
            name="Neutral Card",
            synergy=0.0,
            inclusion=5000,
            potential_decks=10000,
            category="topcards",
        )
        assert card.synergy_pct == 0.0


# ── slugify ──────────────────────────────────────────────────────────────


class TestSlugify:
    def test_simple_name(self) -> None:
        assert slugify("Kaalia of the Vast") == "kaalia-of-the-vast"

    def test_comma_in_name(self) -> None:
        assert slugify("Maralen, Fae Ascendant") == "maralen-fae-ascendant"

    def test_apostrophe(self) -> None:
        assert slugify("Teysa, Orzhov's Scion") == "teysa-orzhovs-scion"

    def test_period(self) -> None:
        assert slugify("Mr. Foxglove") == "mr-foxglove"

    def test_multiple_special_chars(self) -> None:
        assert slugify("Who's, the Dr.?") == "whos-the-dr"

    def test_already_slugified(self) -> None:
        assert slugify("kaalia-of-the-vast") == "kaalia-of-the-vast"

    def test_leading_trailing_hyphens_stripped(self) -> None:
        # Edge case: if name starts or ends with a non-alnum char
        assert slugify(",Weird Name,") == "weird-name"

    def test_mixed_case(self) -> None:
        assert slugify("OKO, Lorwyn Liege") == "oko-lorwyn-liege"

    def test_numbers_preserved(self) -> None:
        assert slugify("Urza's Saga 2") == "urzas-saga-2"


# ── type_distribution ────────────────────────────────────────────────────


class TestTypeDistribution_Extraction:
    def test_typical_data(self, edhrec_data: dict) -> None:
        td = type_distribution(edhrec_data)
        assert td.creature == 28
        assert td.instant == 9
        assert td.sorcery == 8
        assert td.artifact == 10
        assert td.enchantment == 7
        assert td.battle == 0
        assert td.planeswalker == 2
        assert td.land == 36
        assert td.total == 100

    def test_missing_keys_default_zero(self) -> None:
        td = type_distribution({})
        assert td.creature == 0
        assert td.instant == 0
        assert td.land == 0
        assert td.total == 100  # default total_card_count

    def test_partial_data(self) -> None:
        td = type_distribution({"creature": 15, "land": 24, "total_card_count": 60})
        assert td.creature == 15
        assert td.land == 24
        assert td.instant == 0
        assert td.total == 60


# ── mana_curve ───────────────────────────────────────────────────────────


class TestManaCurve:
    def test_typical_data(self, edhrec_data: dict) -> None:
        mc = mana_curve(edhrec_data)
        assert mc == {1: 10, 2: 19, 3: 15, 4: 12, 5: 5, 6: 2, 7: 1}
        assert all(isinstance(k, int) for k in mc)

    def test_missing_panels(self) -> None:
        assert mana_curve({}) == {}

    def test_missing_mana_curve(self) -> None:
        assert mana_curve({"panels": {}}) == {}

    def test_empty_mana_curve(self) -> None:
        assert mana_curve({"panels": {"mana_curve": {}}}) == {}


# ── _extract_cardlist ────────────────────────────────────────────────────


class TestExtractCardlist:
    def test_known_tag(self, edhrec_data: dict) -> None:
        cards = _extract_cardlist(edhrec_data, "highsynergycards")
        assert len(cards) == 2
        assert cards[0].name == "Aurelia, the Warleader"
        assert cards[0].synergy == 0.72
        assert cards[0].category == "highsynergycards"

    def test_unknown_tag(self, edhrec_data: dict) -> None:
        cards = _extract_cardlist(edhrec_data, "nonexistenttag")
        assert cards == []

    def test_empty_data(self) -> None:
        assert _extract_cardlist({}, "highsynergycards") == []

    def test_missing_container(self) -> None:
        assert _extract_cardlist({"container": {}}, "topcards") == []

    def test_card_fields_populated(self, edhrec_data: dict) -> None:
        cards = _extract_cardlist(edhrec_data, "topcards")
        sol = cards[0]
        assert isinstance(sol, SynergyCard)
        assert sol.name == "Sol Ring"
        assert sol.synergy == 0.01
        assert sol.inclusion == 9800
        assert sol.potential_decks == 10000
        assert sol.category == "topcards"

    def test_missing_synergy_defaults_zero(self) -> None:
        data = {
            "container": {
                "json_dict": {
                    "cardlists": [
                        {
                            "tag": "test",
                            "cardviews": [{"name": "Mystery Card", "potential_decks": 100}],
                        }
                    ]
                }
            }
        }
        cards = _extract_cardlist(data, "test")
        assert len(cards) == 1
        assert cards[0].synergy == 0.0
        assert cards[0].inclusion == 0


# ── high_synergy_cards / top_cards / game_changers / new_cards ────────────


class TestCardListGetters:
    def test_high_synergy_cards(self, edhrec_data: dict) -> None:
        cards = high_synergy_cards(edhrec_data)
        assert len(cards) == 2
        assert cards[0].name == "Aurelia, the Warleader"

    def test_top_cards(self, edhrec_data: dict) -> None:
        cards = top_cards(edhrec_data)
        assert len(cards) == 2
        assert cards[0].name == "Sol Ring"

    def test_game_changers(self, edhrec_data: dict) -> None:
        cards = game_changers(edhrec_data)
        assert len(cards) == 1
        assert cards[0].name == "Avacyn, Angel of Hope"

    def test_new_cards(self, edhrec_data: dict) -> None:
        cards = new_cards(edhrec_data)
        assert len(cards) == 1
        assert cards[0].name == "Some New Angel"

    def test_empty_data(self) -> None:
        assert high_synergy_cards({}) == []
        assert top_cards({}) == []
        assert game_changers({}) == []
        assert new_cards({}) == []


# ── cards_by_category ────────────────────────────────────────────────────


class TestCardsByCategory:
    def test_all_categories(self, edhrec_data: dict) -> None:
        result = cards_by_category(edhrec_data)
        assert "highsynergycards" in result
        assert "topcards" in result
        assert "creatures" in result
        assert "lands" in result

    def test_filter_single_category(self, edhrec_data: dict) -> None:
        result = cards_by_category(edhrec_data, category="creatures")
        assert len(result) == 1
        assert "creatures" in result
        assert len(result["creatures"]) == 2

    def test_filter_nonexistent_category(self, edhrec_data: dict) -> None:
        result = cards_by_category(edhrec_data, category="nope")
        assert result == {}

    def test_empty_data(self) -> None:
        assert cards_by_category({}) == {}


# ── all_recommended_cards ────────────────────────────────────────────────


class TestAllRecommendedCards:
    def test_deduplicates_by_name(self, edhrec_data: dict) -> None:
        cards = all_recommended_cards(edhrec_data)
        names = [c.name for c in cards]
        assert len(names) == len(set(names)), "Duplicates found"

    def test_keeps_highest_synergy(self, edhrec_data: dict) -> None:
        cards = all_recommended_cards(edhrec_data)
        aurelia = next(c for c in cards if c.name == "Aurelia, the Warleader")
        # Appears in highsynergycards (0.72) and creatures (0.70) — should keep 0.72
        assert aurelia.synergy == 0.72

    def test_sorted_by_synergy_descending(self, edhrec_data: dict) -> None:
        cards = all_recommended_cards(edhrec_data)
        synergies = [c.synergy for c in cards]
        assert synergies == sorted(synergies, reverse=True)

    def test_empty_data(self) -> None:
        assert all_recommended_cards({}) == []

    def test_includes_cards_from_all_sources(self, edhrec_data: dict) -> None:
        cards = all_recommended_cards(edhrec_data)
        names = {c.name for c in cards}
        # From highsynergycards
        assert "Aurelia, the Warleader" in names
        # From topcards
        assert "Sol Ring" in names
        # From gamechangers
        assert "Avacyn, Angel of Hope" in names
        # From newcards
        assert "Some New Angel" in names
        # From creatures category
        assert "Rune-Scarred Demon" in names
        # From lands category
        assert "Command Tower" in names


# ── combos ───────────────────────────────────────────────────────────────


class TestCombos:
    def test_extracts_combos(self, edhrec_data: dict) -> None:
        result = combos(edhrec_data)
        assert len(result) == 2
        assert isinstance(result[0], Combo)
        assert result[0].description == "Master of Cruelties + Kaalia"

    def test_filters_see_more(self, edhrec_data: dict) -> None:
        result = combos(edhrec_data)
        descriptions = [c.description for c in result]
        assert "See More..." not in descriptions

    def test_empty_data(self) -> None:
        assert combos({}) == []

    def test_no_combocounts_panel(self) -> None:
        assert combos({"panels": {}}) == []

    def test_only_see_more(self) -> None:
        data = {"panels": {"combocounts": [{"value": "See More...", "href": "/combos/x"}]}}
        assert combos(data) == []


# ── combos_url ───────────────────────────────────────────────────────────


class TestCombosUrl:
    def test_returns_full_url(self, edhrec_data: dict) -> None:
        url = combos_url(edhrec_data)
        assert url == "https://edhrec.com/combos/wbr/kaalia-of-the-vast"

    def test_no_see_more_entry(self) -> None:
        data = {
            "panels": {
                "combocounts": [
                    {"value": "Some Combo", "href": "/combos/x"},
                ]
            }
        }
        assert combos_url(data) is None

    def test_empty_data(self) -> None:
        assert combos_url({}) is None

    def test_see_more_empty_href(self) -> None:
        data = {
            "panels": {
                "combocounts": [
                    {"value": "See More...", "href": ""},
                ]
            }
        }
        assert combos_url(data) is None


# ── tags ─────────────────────────────────────────────────────────────────


class TestTags:
    def test_extracts_tags(self, edhrec_data: dict) -> None:
        result = tags(edhrec_data)
        assert len(result) == 4
        assert all(isinstance(t, TagInfo) for t in result)

    def test_sorted_by_count_descending(self, edhrec_data: dict) -> None:
        result = tags(edhrec_data)
        counts = [t.count for t in result]
        assert counts == sorted(counts, reverse=True)
        # Angels (3200) > Dragons (2400) > Demons (1800) > Reanimator (950)
        assert result[0].name == "Angels"
        assert result[1].name == "Dragons"
        assert result[2].name == "Demons"
        assert result[3].name == "Reanimator"

    def test_empty_data(self) -> None:
        assert tags({}) == []

    def test_no_taglinks_panel(self) -> None:
        assert tags({"panels": {}}) == []


# ── num_decks ────────────────────────────────────────────────────────────


class TestNumDecks:
    def test_returns_count(self, edhrec_data: dict) -> None:
        assert num_decks(edhrec_data) == 12345

    def test_missing_key(self) -> None:
        assert num_decks({}) == 0


# ── average_deck_price ───────────────────────────────────────────────────


class TestAverageDeckPrice:
    def test_returns_price(self, edhrec_data: dict) -> None:
        assert average_deck_price(edhrec_data) == 450.75

    def test_missing_key(self) -> None:
        assert average_deck_price({}) == 0.0

    def test_integer_price(self) -> None:
        assert average_deck_price({"avg_price": 300}) == 300.0


# ── _is_stale ────────────────────────────────────────────────────────────


class TestIsStale:
    def test_recent_not_stale(self) -> None:
        recent = datetime.now(UTC).isoformat()
        assert _is_stale(recent, ttl_days=14) is False

    def test_old_is_stale(self) -> None:
        old = (datetime.now(UTC) - timedelta(days=30)).isoformat()
        assert _is_stale(old, ttl_days=14) is True

    def test_exactly_at_boundary(self) -> None:
        # Exactly TTL days ago should be stale (fetched < cutoff)
        boundary = (datetime.now(UTC) - timedelta(days=14)).isoformat()
        assert _is_stale(boundary, ttl_days=14) is True

    def test_just_within_ttl(self) -> None:
        within = (datetime.now(UTC) - timedelta(days=13, hours=23)).isoformat()
        assert _is_stale(within, ttl_days=14) is False

    def test_malformed_timestamp_returns_stale(self) -> None:
        assert _is_stale("not-a-timestamp", ttl_days=14) is True

    def test_zero_ttl_always_stale(self) -> None:
        recent = datetime.now(UTC).isoformat()
        # With TTL 0, even a just-now timestamp is stale
        assert _is_stale(recent, ttl_days=0) is True

    def test_large_ttl_not_stale(self) -> None:
        old = (datetime.now(UTC) - timedelta(days=300)).isoformat()
        assert _is_stale(old, ttl_days=365) is False


# ── open_cache ───────────────────────────────────────────────────────────


class TestOpenCache:
    def test_creates_db(self, tmp_path) -> None:
        db_path = tmp_path / "cache.db"
        conn = open_cache(db_path)
        assert db_path.exists()
        conn.close()

    def test_idempotent(self, tmp_path) -> None:
        db_path = tmp_path / "cache.db"
        conn1 = open_cache(db_path)
        conn1.close()
        # Should not raise on second call
        conn2 = open_cache(db_path)
        tables = conn2.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = [t[0] for t in tables]
        assert "edhrec_commanders" in table_names
        conn2.close()

    def test_schema_columns(self, tmp_path) -> None:
        db_path = tmp_path / "cache.db"
        conn = open_cache(db_path)
        cursor = conn.execute("PRAGMA table_info(edhrec_commanders)")
        columns = {row[1] for row in cursor.fetchall()}
        assert columns == {
            "sanitized_name",
            "name",
            "num_decks",
            "full_json",
            "fetched_at",
        }
        conn.close()
