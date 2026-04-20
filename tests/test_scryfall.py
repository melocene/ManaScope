"""Tests for manascope.scryfall — batch name fetching and cache behaviour."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from manascope.scryfall import (
    _read_capped,
    _ResponseTooLarge,
    _upsert_cards,
    fetch_cards_by_names,
    get_card_by_name,
    open_cache,
)

# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture()
def cache_conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """Open a fresh SQLite cache with the real schema."""
    db = tmp_path / "test_cache.db"
    conn = open_cache(db)
    yield conn
    conn.close()


def _make_card(
    name: str,
    set_code: str = "tst",
    collector_number: str = "1",
    mana_cost: str = "{1}",
    **extra: object,
) -> dict:
    """Build a minimal Scryfall-like card dict."""
    card: dict = {
        "name": name,
        "set": set_code,
        "collector_number": collector_number,
        "mana_cost": mana_cost,
        "type_line": "Creature",
        "oracle_text": "",
        "cmc": 1.0,
        "colors": [],
        "color_identity": [],
        "legalities": {},
    }
    card.update(extra)
    return card


def _seed_cache(conn: sqlite3.Connection, cards: list[dict]) -> None:
    """Insert card dicts into the cache."""
    _upsert_cards(conn, cards)


def _make_mock_response(body: dict, status_code: int = 200) -> MagicMock:
    """Build a MagicMock response that mimics requests.Response for _read_capped.

    Sets iter_content to yield the JSON-encoded body, plus a Content-Length
    header, so the streaming size-cap path works transparently.
    """
    import json as _json

    payload = _json.dumps(body).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.headers = {"Content-Length": str(len(payload))}
    mock_resp.content = payload
    mock_resp.iter_content.return_value = iter([payload])
    mock_resp.json.return_value = body
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


# ── get_card_by_name ─────────────────────────────────────────────────────


class TestGetCardByName:
    def test_exact_match(self, cache_conn: sqlite3.Connection) -> None:
        card = _make_card("Sol Ring", "c21", "263")
        _seed_cache(cache_conn, [card])
        result = get_card_by_name(cache_conn, "Sol Ring")
        assert result is not None
        assert result["name"] == "Sol Ring"

    def test_case_insensitive(self, cache_conn: sqlite3.Connection) -> None:
        card = _make_card("Sol Ring", "c21", "263")
        _seed_cache(cache_conn, [card])
        result = get_card_by_name(cache_conn, "sol ring")
        assert result is not None
        assert result["name"] == "Sol Ring"

    def test_not_found(self, cache_conn: sqlite3.Connection) -> None:
        result = get_card_by_name(cache_conn, "Nonexistent Card")
        assert result is None


# ── fetch_cards_by_names — cache hits ────────────────────────────────────


class TestFetchCardsByNamesCacheHits:
    """Tests where all cards are already cached — no network calls."""

    def test_all_cached(self, cache_conn: sqlite3.Connection) -> None:
        cards = [
            _make_card("Sol Ring", "c21", "263"),
            _make_card("Lightning Bolt", "m10", "146"),
        ]
        _seed_cache(cache_conn, cards)

        result = fetch_cards_by_names(cache_conn, ["Sol Ring", "Lightning Bolt"])
        assert "Sol Ring" in result
        assert "Lightning Bolt" in result
        assert len(result) == 2

    def test_empty_list(self, cache_conn: sqlite3.Connection) -> None:
        result = fetch_cards_by_names(cache_conn, [])
        assert result == {}

    def test_result_keyed_by_requested_name(self, cache_conn: sqlite3.Connection) -> None:
        """Result dict keys should match the input names, not canonical names."""
        card = _make_card("Sol Ring", "c21", "263")
        _seed_cache(cache_conn, [card])
        # Request with different casing — key should be the *requested* name
        result = fetch_cards_by_names(cache_conn, ["sol ring"])
        assert "sol ring" in result
        assert result["sol ring"]["name"] == "Sol Ring"

    def test_dfc_found_via_like_fallback(self, cache_conn: sqlite3.Connection) -> None:
        """DFC cards stored as 'Front // Back' should be found when queried by front name."""
        card = _make_card("Virtue of Knowledge // Vantress Visions", "woe", "76")
        _seed_cache(cache_conn, [card])

        result = fetch_cards_by_names(cache_conn, ["Virtue of Knowledge"])
        assert "Virtue of Knowledge" in result
        assert result["Virtue of Knowledge"]["name"] == "Virtue of Knowledge // Vantress Visions"

    def test_dfc_exact_name_also_works(self, cache_conn: sqlite3.Connection) -> None:
        """Full DFC name should also resolve from cache."""
        card = _make_card("Virtue of Knowledge // Vantress Visions", "woe", "76")
        _seed_cache(cache_conn, [card])

        result = fetch_cards_by_names(cache_conn, ["Virtue of Knowledge // Vantress Visions"])
        assert "Virtue of Knowledge // Vantress Visions" in result

    def test_mixed_cached_and_dfc(self, cache_conn: sqlite3.Connection) -> None:
        cards = [
            _make_card("Sol Ring", "c21", "263"),
            _make_card("Sheoldred // The True Scriptures", "mom", "125"),
        ]
        _seed_cache(cache_conn, cards)

        result = fetch_cards_by_names(cache_conn, ["Sol Ring", "Sheoldred"])
        assert "Sol Ring" in result
        assert "Sheoldred" in result
        assert len(result) == 2


# ── fetch_cards_by_names — network batching ──────────────────────────────


class TestFetchCardsByNamesBatchFetch:
    """Tests that verify batch network fetching via /cards/collection."""

    def test_uncached_cards_are_batch_fetched(self, cache_conn: sqlite3.Connection) -> None:
        """Cards not in cache should be fetched via a single batch POST."""
        mock_card_a = _make_card("Card A", "tst", "1")
        mock_card_b = _make_card("Card B", "tst", "2")

        mock_resp = _make_mock_response(
            {
                "data": [mock_card_a, mock_card_b],
                "not_found": [],
            }
        )

        mock_session = MagicMock()
        mock_session.post.return_value = mock_resp

        with patch("manascope.scryfall._make_session", return_value=mock_session):
            result = fetch_cards_by_names(cache_conn, ["Card A", "Card B"])

        assert "Card A" in result
        assert "Card B" in result
        # Should be a single batch call
        assert mock_session.post.call_count == 1
        # Verify the identifiers sent
        call_kwargs = mock_session.post.call_args
        identifiers = (
            call_kwargs[1]["json"]["identifiers"] if "json" in call_kwargs[1] else call_kwargs[0][1]
        )
        assert {"name": "Card A"} in identifiers
        assert {"name": "Card B"} in identifiers

    def test_cached_cards_skip_network(self, cache_conn: sqlite3.Connection) -> None:
        """Already-cached cards should not trigger any network call."""
        card = _make_card("Cached Card", "tst", "99")
        _seed_cache(cache_conn, [card])

        mock_session = MagicMock()
        with patch("manascope.scryfall._make_session", return_value=mock_session):
            result = fetch_cards_by_names(cache_conn, ["Cached Card"])

        assert "Cached Card" in result
        mock_session.post.assert_not_called()

    def test_partial_cache_only_fetches_missing(self, cache_conn: sqlite3.Connection) -> None:
        """When some cards are cached, only the missing ones hit the network."""
        cached = _make_card("Already Here", "tst", "1")
        _seed_cache(cache_conn, [cached])

        fetched = _make_card("New Card", "tst", "2")
        mock_resp = _make_mock_response({"data": [fetched], "not_found": []})

        mock_session = MagicMock()
        mock_session.post.return_value = mock_resp

        with patch("manascope.scryfall._make_session", return_value=mock_session):
            result = fetch_cards_by_names(cache_conn, ["Already Here", "New Card"])

        assert "Already Here" in result
        assert "New Card" in result
        # Only one batch call for the missing card
        assert mock_session.post.call_count == 1
        identifiers = mock_session.post.call_args[1]["json"]["identifiers"]
        names_sent = [i["name"] for i in identifiers]
        assert "New Card" in names_sent
        assert "Already Here" not in names_sent

    def test_not_found_triggers_fuzzy_fallback(self, cache_conn: sqlite3.Connection) -> None:
        """Cards returned as not_found by the batch endpoint should fall back to fuzzy lookup."""
        mock_batch_resp = _make_mock_response(
            {
                "data": [],
                "not_found": [{"name": "Sheoldred"}],
            }
        )

        mock_session = MagicMock()
        mock_session.post.return_value = mock_batch_resp

        fuzzy_card = _make_card("Sheoldred // The True Scriptures", "mom", "125")

        with (
            patch("manascope.scryfall._make_session", return_value=mock_session),
            patch("manascope.scryfall.fetch_card_by_name", return_value=fuzzy_card) as mock_fuzzy,
        ):
            result = fetch_cards_by_names(cache_conn, ["Sheoldred"])

        # Fuzzy fallback should have been called for "Sheoldred"
        mock_fuzzy.assert_called_once_with(cache_conn, "Sheoldred", fuzzy=True)
        # Result should be keyed by requested name
        assert "Sheoldred" in result
        assert result["Sheoldred"]["name"] == "Sheoldred // The True Scriptures"

    def test_dfc_batch_result_keyed_by_requested_name(self, cache_conn: sqlite3.Connection) -> None:
        """When the batch returns a DFC with full name, the result key should be the requested front-face name."""
        dfc = _make_card("Virtue of Knowledge // Vantress Visions", "woe", "76")

        mock_resp = _make_mock_response({"data": [dfc], "not_found": []})

        mock_session = MagicMock()
        mock_session.post.return_value = mock_resp

        with patch("manascope.scryfall._make_session", return_value=mock_session):
            result = fetch_cards_by_names(cache_conn, ["Virtue of Knowledge"])

        # Key should be the requested name, not the canonical DFC name
        assert "Virtue of Knowledge" in result
        assert "Virtue of Knowledge // Vantress Visions" not in result

    def test_force_refresh_skips_cache(self, cache_conn: sqlite3.Connection) -> None:
        """force_refresh=True should re-fetch even if the card is cached."""
        old_card = _make_card("Sol Ring", "c21", "263")
        _seed_cache(cache_conn, [old_card])

        new_card = _make_card("Sol Ring", "fdn", "999", mana_cost="{1}")
        mock_resp = _make_mock_response({"data": [new_card], "not_found": []})

        mock_session = MagicMock()
        mock_session.post.return_value = mock_resp

        with patch("manascope.scryfall._make_session", return_value=mock_session):
            result = fetch_cards_by_names(cache_conn, ["Sol Ring"], force_refresh=True)

        assert "Sol Ring" in result
        # Should have made a network call despite being cached
        assert mock_session.post.call_count == 1

    def test_fetched_cards_are_persisted_to_cache(self, cache_conn: sqlite3.Connection) -> None:
        """Cards fetched from the network should be written to the cache."""
        card = _make_card("New Card", "tst", "42")

        mock_resp = _make_mock_response({"data": [card], "not_found": []})

        mock_session = MagicMock()
        mock_session.post.return_value = mock_resp

        with patch("manascope.scryfall._make_session", return_value=mock_session):
            fetch_cards_by_names(cache_conn, ["New Card"])

        # Now it should be in cache
        cached = get_card_by_name(cache_conn, "New Card")
        assert cached is not None
        assert cached["name"] == "New Card"


# ── DFC name normalization for verify ────────────────────────────────────


class TestDfcNameNormalization:
    """Test that the verify logic correctly normalizes single-slash DFC names
    to double-slash for collection matching. This tests the normalization
    logic extracted from cli.py's verify command."""

    @staticmethod
    def _check_owned(name: str, owned: set[str]) -> bool:
        """Reproduce the verify matching logic from cli.py."""
        low = name.lower()
        normalized = low.replace(" / ", " // ")
        if normalized in owned:
            return True
        front = normalized.split(" // ", 1)[0] if " // " in normalized else low
        return front in owned

    def test_exact_match(self) -> None:
        owned = {"sol ring"}
        assert self._check_owned("Sol Ring", owned)

    def test_dfc_single_slash_normalized(self) -> None:
        """Decklist single-slash should match collection double-slash."""
        owned = {"virtue of loyalty // ardenvale fealty"}
        assert self._check_owned("Virtue of Loyalty / Ardenvale Fealty", owned)

    def test_dfc_front_face_only_in_collection(self) -> None:
        """MTGA collection stores front face only; decklist has full name."""
        owned = {"virtue of loyalty"}
        assert self._check_owned("Virtue of Loyalty / Ardenvale Fealty", owned)

    def test_plain_card_not_owned(self) -> None:
        owned = {"sol ring"}
        assert not self._check_owned("Lightning Bolt", owned)

    def test_dfc_not_owned(self) -> None:
        owned = {"sol ring"}
        assert not self._check_owned("Virtue of Loyalty / Ardenvale Fealty", owned)

    def test_adventure_card_single_slash(self) -> None:
        """Adventure cards like 'Bramble Familiar / Fetch Quest'."""
        owned = {"bramble familiar // fetch quest"}
        assert self._check_owned("Bramble Familiar / Fetch Quest", owned)


# -- _read_capped streaming size cap ------------------------------------------


class TestReadCapped:
    """Cover the streaming response-size guard."""

    def test_small_response_returned_intact(self) -> None:
        payload = b'{"data": [1, 2, 3]}'
        resp = MagicMock()
        resp.headers = {"Content-Length": str(len(payload))}
        resp.iter_content.return_value = iter([payload])
        assert _read_capped(resp, limit=1024) == payload

    def test_content_length_over_limit_short_circuits(self) -> None:
        resp = MagicMock()
        resp.headers = {"Content-Length": "9999"}
        resp.iter_content.return_value = iter([b"" for _ in range(0)])
        with pytest.raises(_ResponseTooLarge):
            _read_capped(resp, limit=100)
        resp.close.assert_called_once()
        resp.iter_content.assert_not_called()

    def test_streamed_body_over_limit_aborts_mid_read(self) -> None:
        """No Content-Length header; body exceeds limit only after streaming."""
        resp = MagicMock()
        resp.headers = {}
        # 3 chunks of 60 bytes each = 180 total; limit 100 triggers on chunk 2.
        resp.iter_content.return_value = iter([b"x" * 60, b"x" * 60, b"x" * 60])
        with pytest.raises(_ResponseTooLarge):
            _read_capped(resp, limit=100)
        resp.close.assert_called_once()

    def test_malformed_content_length_falls_through_to_stream(self) -> None:
        payload = b"hello"
        resp = MagicMock()
        resp.headers = {"Content-Length": "not-an-int"}
        resp.iter_content.return_value = iter([payload])
        assert _read_capped(resp, limit=1024) == payload
