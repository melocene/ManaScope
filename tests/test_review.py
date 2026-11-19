"""Tests for manascope.review EDHREC cross-reference helpers."""

import pytest
import pytest_mock

from manascope.edhrec import RecommendedCard
from manascope.review import cut_review, lowest_lift_non_staples, run_edhrec_section


def _card(name: str, lift: float, inclusion_pct: float) -> RecommendedCard:
    return RecommendedCard(name, 0.0, round(inclusion_pct * 10), 1000, "x", lift=lift)


def _edhrec_payload(cards: list[tuple[str, float, int]]) -> dict:
    """EDHREC payload with one card list of (name, lift, decks-out-of-1000)."""
    views = [
        {"name": name, "lift": lift, "num_decks": decks, "potential_decks": 1000}
        for name, lift, decks in cards
    ]
    return {"container": {"json_dict": {"cardlists": [{"tag": "x", "cardviews": views}]}}}


class TestLowestLiftNonStaples:
    def test_skips_staples(self) -> None:
        cards = [
            _card("Engine Piece", 8.0, 30),
            _card("Niche Pick", 1.5, 10),
            _card("Sol Ring", 1.02, 98),
        ]
        assert [c.name for c in lowest_lift_non_staples(cards)] == ["Niche Pick", "Engine Piece"]

    def test_popular_with_commander_is_not_a_staple(self) -> None:
        # 71% of this commander's decks but ~8% of decks in these colours: a core card, not a staple.
        cards = [_card("Core Card", 9.39, 71), _card("Niche Pick", 1.5, 10)]
        assert [c.name for c in lowest_lift_non_staples(cards)] == ["Niche Pick", "Core Card"]

    def test_lowest_first_and_limited(self) -> None:
        cards = [_card(f"C{i}", 10.0 - i, 20) for i in range(8)]
        assert [c.name for c in lowest_lift_non_staples(cards, n=3)] == ["C7", "C6", "C5"]


class TestCutReview:
    RECS = (
        _card("Engine Piece", 8.0, 30),
        _card("Delver of Secrets", 3.0, 20),
        _card("Niche Pick", 1.5, 10),
        _card("Sol Ring", 1.02, 98),
        _card("Swamp", 1.0, 90),
    )

    def test_splits_deck_cards(self) -> None:
        deck = [
            "Kaalia of the Vast",
            "Engine Piece",
            "Niche Pick",
            "Sol Ring",
            "Swamp",
            "Pet Card",
        ]
        lowest, staples, not_on = cut_review(list(self.RECS), deck, "Kaalia of the Vast")
        assert [c.name for c in lowest] == ["Niche Pick", "Engine Piece"]
        assert [c.name for c in staples] == ["Sol Ring"]  # basics are left out
        assert not_on == ["Pet Card"]  # commander and basics are left out

    def test_double_faced_deck_card_matches_front_face(self) -> None:
        deck = ["Delver of Secrets // Insectile Aberration"]
        lowest, _, not_on = cut_review(list(self.RECS), deck, "Commander")
        assert [c.name for c in lowest] == ["Delver of Secrets"]
        assert not_on == []


class TestRunEdhrecSection:
    CARDS = (
        ("Engine A", 9.0, 300),
        ("Engine B", 7.0, 250),
        ("Engine C", 5.0, 200),
        ("Niche Pick", 1.4, 40),
        ("Arcane Signet", 1.1, 900),
        ("Sol Ring", 1.02, 980),
    )
    DECK = ("X", *(name for name, _, _ in CARDS), "Pet Card")

    @pytest.fixture(autouse=True)
    def _cached_and_legal(self, mocker: pytest_mock.MockerFixture) -> None:
        mocker.patch(
            "manascope.review.sc.get_card_by_name",
            return_value={"type_line": "Artifact", "cmc": 1},
        )
        mocker.patch("manascope.review.deck.is_legal", return_value=True)

    def _run(self, mocker: pytest_mock.MockerFixture, **kwargs: object) -> dict | None:
        params: dict = {
            "commander_name": "X",
            "deck_names": {name.lower() for name in self.DECK},
            "conn": mocker.Mock(),
            "owned": {},
            "fmt": "commander",
            "top_n": 3,  # cut review must still see cards outside the top N
            "edhrec_data": _edhrec_payload(list(self.CARDS)),
            "deck_cards": list(self.DECK),
        }
        params.update(kwargs)
        return run_edhrec_section(**params)

    def test_json_cut_review(self, mocker: pytest_mock.MockerFixture) -> None:
        out = self._run(mocker, json_flag=True, return_data=True)
        assert out is not None
        assert out["in_deck"][0]["inclusion"] == 30.0
        cr = out["cut_review"]
        assert next(c["name"] for c in cr["lowest_lift"]) == "Niche Pick"
        sol_ring = next(c for c in cr["staples"] if c["name"] == "Sol Ring")
        assert sol_ring["staple"] is True
        assert sol_ring["colour_share"] == 96.1
        assert cr["not_on_edhrec"] == ["Pet Card"]
        assert out["stats"]["top_lift"] == 9.0
        assert out["stats"]["lift_compressed"] is False

    def test_compressed_lift_is_flagged(
        self, mocker: pytest_mock.MockerFixture, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Lift can't exceed 1 / (commander's share of its colours' decks).
        flat = _edhrec_payload([("Card A", 1.8, 300), ("Card B", 1.7, 100)])
        out = self._run(mocker, edhrec_data=flat, json_flag=True, return_data=True)
        assert out is not None
        assert out["stats"]["lift_compressed"] is True
        self._run(mocker, edhrec_data=flat, agent=True)
        assert "[Note] Lift is compressed (top 1.80x)" in capsys.readouterr().out

    def test_text_box(
        self, mocker: pytest_mock.MockerFixture, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._run(mocker)
        box = capsys.readouterr().out.split("Cut review", 1)[1].split("└─", 1)[0]
        ranked, rest = box.split("Staples", 1)
        staples, not_on = rest.split("Not on EDHREC", 1)
        assert "Niche Pick" in ranked
        assert "Sol Ring" not in ranked
        sol_ring_row = next(line for line in staples.splitlines() if "Sol Ring" in line)
        assert "1.02x" in sol_ring_row
        assert "98%" in sol_ring_row
        assert "~96% of decks in these colours" in sol_ring_row
        assert "Pet Card" in not_on

    def test_agent_lines(
        self, mocker: pytest_mock.MockerFixture, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._run(
            mocker,
            deck_names={"x"},
            deck_cards=["X", "Sol Ring", "Pet Card"],
            owned={"niche pick": {"name": "Niche Pick", "count": 1}},
            top_n=80,
            agent=True,
        )
        out = capsys.readouterr().out
        assert "Niche Pick(1.40x, inc 4%)" in out
        assert "[Staples In Deck] Sol Ring(1.02x, inc 98%, colours ~96%)" in out
        assert "[Not On EDHREC] (1) Pet Card" in out
