"""Fetches and caches EDHREC commander data (type distribution, lift, combos, themes).

Shares the SQLite cache in ``.cache/cache.db`` with :mod:`manascope.scryfall`.
Commander pages are cached with a 14-day TTL; the raw JSON is stored as-is and
parsed on demand via helper functions (``type_distribution``, ``high_lift_cards``,
``mana_curve``, ``combos``, ``tags``, etc.).  Lookup accepts either a display name
or an EDHREC slug.  Used by ``cli.py`` (edhrec/prime commands) and ``review.py``.
"""

import json
import re
import sqlite3
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NamedTuple

import requests

from manascope import DB_PATH, MAX_RESPONSE_BYTES

# Constants

JSON_API_URL = "https://json.edhrec.com/pages/commanders/{slug}.json"
DEFAULT_TTL_DAYS = 14
# Cached pages without EDHREC lift scores (pre-October 2026 payloads) are
# re-fetched after this many days instead of DEFAULT_TTL_DAYS. Not zero, so a
# page EDHREC still serves without lift is requested at most once per day.
PRE_LIFT_TTL_DAYS = 1
REQUEST_DELAY = 0.30  # 300 ms between requests (be a good citizen)
# Cards in >= 50% of decks in a commander's colours are "staples" (EDHREC's
# "ubiquitous"). Their lift can't exceed 2.0, so lift can't judge them. See
# https://edhrec.com/articles/from-synergy-to-lift-the-math-behind-edhrecs-new-era
STAPLE_COLOUR_PCT = 50.0
# Top lift at or below this means one commander dominates its colours (often a
# precon), so lift barely separates cards.
COMPRESSED_LIFT_MAX = 2.0
# Network timeout (seconds). EDHREC responses are small JSON pages, so
# a shorter timeout than Scryfall's /cards/collection payload is fine.
REQUEST_TIMEOUT = 15

USER_AGENT = "manascope/0.1 (personal deckbuilding helper; non-commercial)"
ACCEPT = "application/json"

# Data model


class TypeDistribution(NamedTuple):
    """Average type distribution for a commander's decks."""

    creature: int
    instant: int
    sorcery: int
    artifact: int
    enchantment: int
    battle: int
    planeswalker: int
    land: int
    total: int

    def as_percentages(self) -> dict[str, float]:
        """Return each type as a percentage of total_card_count.

        Useful for cross-format comparison since EDHREC averages are from
        100-card Commander decks and don't directly apply to 60-card
        Standard Brawl or other formats.
        """
        if self.total == 0:
            return {f.lower(): 0.0 for f in self._fields if f != "total"}
        return {
            field: round(getattr(self, field) / self.total * 100, 1)
            for field in self._fields
            if field != "total"
        }

    def scaled_to(self, deck_size: int) -> dict[str, int]:
        """Scale the average counts to a different deck size (e.g. 60 for Standard Brawl).

        Returns rounded integers that sum to deck_size.

        Uses largest-remainder method to ensure the total is exact.
        """
        if self.total == 0:
            return {f: 0 for f in self._fields if f != "total"}

        fields = [f for f in self._fields if f != "total"]
        raw = {f: getattr(self, f) / self.total * deck_size for f in fields}

        # Floor everything first
        floored = {f: int(v) for f, v in raw.items()}
        remainders = {f: raw[f] - floored[f] for f in fields}
        shortfall = deck_size - sum(floored.values())

        # Distribute remaining slots to largest remainders
        for f in sorted(remainders, key=lambda k: remainders[k], reverse=True):
            if shortfall <= 0:
                break
            floored[f] += 1
            shortfall -= 1

        return floored


class RecommendedCard(NamedTuple):
    """A card recommendation from EDHREC with lift/inclusion data.

    ``lift`` is EDHREC's replacement for synergy (``1.0`` = no association with
    the commander); see
    https://edhrec.com/articles/from-synergy-to-lift-the-math-behind-edhrecs-new-era.
    ``synergy`` is kept only to rank pre-lift cache entries.
    """

    name: str
    synergy: float  # legacy synergy score as a fraction (0.61 = 61%)
    inclusion: int  # number of decks including this card
    potential_decks: int  # total decks sampled
    category: str  # which card list this came from (e.g. "highliftcards")
    lift: float | None = None  # lift multiplier; None for pre-lift payloads

    @property
    def inclusion_pct(self) -> float:
        """Inclusion rate as a percentage."""
        if self.potential_decks == 0:
            return 0.0
        return round(self.inclusion / self.potential_decks * 100, 1)

    @property
    def synergy_pct(self) -> float:
        """Legacy synergy score as a percentage."""
        return round(self.synergy * 100, 1)

    @property
    def rank_key(self) -> tuple[bool, float]:
        """Sort key: lift when available, legacy synergy otherwise.

        Cards with lift always outrank cards without it, so the two scales
        are never compared directly.
        """
        if self.lift is not None:
            return (True, self.lift)
        return (False, self.synergy)

    @property
    def score_label(self) -> str:
        """Compact score for text output: ``3.26x`` (lift) or ``12.0%`` (legacy synergy)."""
        if self.lift is not None:
            return f"{self.lift:.2f}x"
        return f"{self.synergy_pct}%"

    @property
    def score_fields(self) -> dict[str, float | None]:
        """Score keys for JSON output.

        ``lift`` is always present. ``synergy`` (percent) is added only when
        lift is unavailable, i.e. the cached EDHREC page predates lift.
        """
        if self.lift is not None:
            return {"lift": round(self.lift, 2)}
        return {"lift": None, "synergy": self.synergy_pct}

    @property
    def colour_pct(self) -> float | None:
        """Estimated % of decks in the commander's colours that run this card.

        inclusion / lift, or inclusion - synergy on pre-lift pages (the two agree).
        Approximate: EDHREC also adjusts deck counts for release dates.
        """
        if self.lift is not None:
            return round(min(self.inclusion_pct / self.lift, 100.0), 1) if self.lift > 0 else None
        if self.potential_decks:
            return round(max(self.inclusion_pct - self.synergy_pct, 0.0), 1)
        return None

    @property
    def is_staple(self) -> bool:
        """True if most decks in these colours run this card, whatever the commander."""
        share = self.colour_pct
        return share is not None and share >= STAPLE_COLOUR_PCT


class Combo(NamedTuple):
    """A combo found in EDHREC data."""

    description: str
    href: str


class TagInfo(NamedTuple):
    """A deck theme/archetype tag with its deck count."""

    name: str
    slug: str
    deck_count: int


# Schema

SCHEMA = """
CREATE TABLE IF NOT EXISTS edhrec_commanders (
    sanitized_name TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    num_decks      INTEGER NOT NULL DEFAULT 0,
    full_json      TEXT NOT NULL,
    fetched_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Connection / schema helpers


def open_cache(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Open (or create) the SQLite cache and ensure the EDHREC table exists.

    Safe to call multiple times - CREATE TABLE IF NOT EXISTS is idempotent.
    This uses the shared .cache/cache.db database.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    # Match the performance pragmas used by scryfall.open_cache so both
    # modules configure the shared cache identically regardless of which
    # one opens it first.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


# Slug helpers


def slugify(name: str) -> str:
    """Convert a commander display name to an EDHREC URL slug.

    Examples:
        "Maralen, Fae Ascendant"  -> "maralen-fae-ascendant"
        "Kaalia of the Vast"      -> "kaalia-of-the-vast"
        "Oko, Lorwyn Liege"       -> "oko-lorwyn-liege"
        "Esika, God of the Tree // The Prismatic Bridge" -> "esika-god-of-the-tree"
    """
    slug = name.lower()
    # EDHREC pages for double-faced commanders use the front-face slug only.
    if " // " in slug:
        slug = slug.split(" // ", 1)[0]
    slug = re.sub(r"[',.]", "", slug)  # strip apostrophes, commas, periods
    slug = re.sub(r"[^a-z0-9]+", "-", slug)  # non-alphanumeric -> hyphen
    slug = slug.strip("-")
    return slug


# Internal helpers


def _make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": ACCEPT})
    return session


class _ResponseTooLarge(Exception):
    """Raised when a streamed response exceeds MAX_RESPONSE_BYTES."""


def _read_capped(resp: requests.Response, limit: int = MAX_RESPONSE_BYTES) -> bytes:
    """Read a response body while enforcing a hard byte cap (streamed)."""
    content_length = resp.headers.get("Content-Length")
    if content_length is not None:
        try:
            if int(content_length) > limit:
                resp.close()
                raise _ResponseTooLarge(int(content_length))
        except ValueError:
            pass

    chunks: list[bytes] = []
    total = 0
    for chunk in resp.iter_content(chunk_size=65536):
        if not chunk:
            continue
        total += len(chunk)
        if total > limit:
            resp.close()
            raise _ResponseTooLarge(total)
        chunks.append(chunk)
    return b"".join(chunks)


def _is_stale(fetched_at: str, ttl_days: int) -> bool:
    """Check if a cached entry is older than the TTL."""
    try:
        fetched = datetime.fromisoformat(fetched_at).replace(tzinfo=UTC)
    except ValueError:
        # If we can't parse the timestamp, treat as stale
        return True
    cutoff = datetime.now(UTC) - timedelta(days=ttl_days)
    return fetched < cutoff


def _predates_lift(data: dict[str, Any]) -> bool:
    """True if the payload has card recommendations but no EDHREC lift scores."""
    for cl in data.get("container", {}).get("json_dict", {}).get("cardlists", []):
        for cv in cl.get("cardviews", []):
            return "lift" not in cv
    return False


def _get_cached(conn: sqlite3.Connection, slug: str) -> tuple[dict[str, Any], str] | None:
    """Return (parsed_json, fetched_at) from cache, or None if not cached."""
    row = conn.execute(
        "SELECT full_json, fetched_at FROM edhrec_commanders WHERE sanitized_name = ?",
        (slug,),
    ).fetchone()
    if row is None:
        return None
    return json.loads(row[0]), row[1]


def _upsert_commander(conn: sqlite3.Connection, slug: str, data: dict[str, Any]) -> None:
    """Insert or update a commander's EDHREC data in the cache."""
    name = data.get("header", slug).replace(" (Commander)", "").strip()
    num_decks_sampled = num_decks(data)
    full_json = json.dumps(data)

    conn.execute(
        """
        INSERT INTO edhrec_commanders (sanitized_name, name, num_decks, full_json)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(sanitized_name) DO UPDATE SET
            name       = excluded.name,
            num_decks  = excluded.num_decks,
            full_json  = excluded.full_json,
            fetched_at = datetime('now')
        """,
        (slug, name, num_decks_sampled, full_json),
    )
    conn.commit()


# Public fetch API (cache-first; network only for misses or stale data)


def fetch_commander(
    conn: sqlite3.Connection,
    commander: str,
    *,
    ttl_days: int = DEFAULT_TTL_DAYS,
    force_refresh: bool = False,
) -> dict[str, Any] | None:
    """Return the full EDHREC JSON data for a commander.

    Cache-first: if fresh data exists in the cache, returns it without
    hitting the network.  Set force_refresh=True to bypass the cache.

    Args:
        conn: SQLite connection (from open_cache())
        commander: Either a sanitized slug ("maralen-fae-ascendant") or
                   a display name ("Maralen, Fae Ascendant")
        ttl_days: Maximum age of cached data in days before re-fetching
        force_refresh: If True, always fetch from the network

    Returns:
        The parsed JSON dict, or None if the commander page doesn't exist.
    """
    slug = slugify(commander) if " " in commander or "," in commander else commander

    if not force_refresh:
        cached = _get_cached(conn, slug)
        if cached is not None:
            data, fetched_at = cached
            pre_lift = _predates_lift(data)
            effective_ttl = min(ttl_days, PRE_LIFT_TTL_DAYS) if pre_lift else ttl_days
            if not _is_stale(fetched_at, effective_ttl):
                return data
            reason = "predates EDHREC lift scores" if pre_lift else "stale"
            print(
                f"  [edhrec] cache {reason} for {slug!r}, re-fetching...",
                file=sys.stderr,
            )

    url = JSON_API_URL.format(slug=slug)
    session = _make_session()
    print(f"  [edhrec] fetching {url}...", file=sys.stderr)

    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT, stream=True)
        if resp.status_code == 404:
            print(
                f"  [edhrec] WARNING: commander page not found - {slug!r}",
                file=sys.stderr,
            )
            time.sleep(REQUEST_DELAY)
            session.close()
            return None
        resp.raise_for_status()
        data = json.loads(_read_capped(resp))
    except _ResponseTooLarge as exc:
        print(
            f"  [edhrec] ERROR: response too large (>{int(exc.args[0])} bytes), skipping.",
            file=sys.stderr,
        )
        # Fall back to stale cache if available
        cached = _get_cached(conn, slug)
        if cached is not None:
            print(
                f"  [edhrec] using stale cache for {slug!r}",
                file=sys.stderr,
            )
            session.close()
            return cached[0]
        session.close()
        return None
    except requests.RequestException as exc:
        print(f"  [edhrec] ERROR fetching {slug!r}: {exc}", file=sys.stderr)
        # Fall back to stale cache if available
        cached = _get_cached(conn, slug)
        if cached is not None:
            print(
                f"  [edhrec] using stale cache for {slug!r}",
                file=sys.stderr,
            )
            return cached[0]
        session.close()
        return None

    _upsert_commander(conn, slug, data)
    time.sleep(REQUEST_DELAY)
    session.close()
    return data


# Extraction helpers - parse commonly-needed data from cached JSON


def type_distribution(data: dict[str, Any]) -> TypeDistribution:
    """Extract the average type distribution from EDHREC commander data.

    Note: These counts are from 100-card Commander decks.  Use
    .as_percentages() or .scaled_to(60) for cross-format comparison.
    """
    return TypeDistribution(
        creature=data.get("creature", 0),
        instant=data.get("instant", 0),
        sorcery=data.get("sorcery", 0),
        artifact=data.get("artifact", 0),
        enchantment=data.get("enchantment", 0),
        battle=data.get("battle", 0),
        planeswalker=data.get("planeswalker", 0),
        land=data.get("land", 0),
        total=data.get("total_card_count", 100),
    )


def mana_curve(data: dict[str, Any]) -> dict[int, int]:
    """Extract the average mana curve from EDHREC commander data.

    Returns a dict of {mana_value: count}, e.g. {1: 10, 2: 19, 3: 15, ...}.
    """
    raw = data.get("panels", {}).get("mana_curve", {})
    return {int(k): v for k, v in raw.items()}


def _card_from_view(cv: dict[str, Any], tag: str) -> RecommendedCard:
    """Build a RecommendedCard from one EDHREC ``cardviews`` entry."""
    lift = cv.get("lift")
    return RecommendedCard(
        name=cv["name"],
        synergy=cv.get("synergy", 0.0),
        inclusion=cv.get("num_decks", cv.get("inclusion", 0)),
        potential_decks=cv.get("potential_decks", 0),
        category=tag,
        lift=float(lift) if lift is not None else None,
    )


def _extract_cardlist(data: dict[str, Any], tag: str) -> list[RecommendedCard]:
    """Extract a card list by its tag from the EDHREC JSON structure."""
    cardlists = data.get("container", {}).get("json_dict", {}).get("cardlists", [])
    for cl in cardlists:
        if cl.get("tag") == tag:
            return [_card_from_view(cv, tag) for cv in cl.get("cardviews", [])]
    return []


def high_lift_cards(data: dict[str, Any]) -> list[RecommendedCard]:
    """Cards with the highest lift for this commander.

    Falls back to the legacy ``highsynergycards`` list for pre-lift cache entries.
    """
    return _extract_cardlist(data, "highliftcards") or _extract_cardlist(data, "highsynergycards")


def top_cards(data: dict[str, Any]) -> list[RecommendedCard]:
    """Most-included cards overall (beyond just high lift)."""
    return _extract_cardlist(data, "topcards")


def game_changers(data: dict[str, Any]) -> list[RecommendedCard]:
    """Powerful staples that appear in many decks for this commander."""
    return _extract_cardlist(data, "gamechangers")


def new_cards(data: dict[str, Any]) -> list[RecommendedCard]:
    """Recently printed cards appearing in this commander's decks."""
    return _extract_cardlist(data, "newcards")


def cards_by_category(
    data: dict[str, Any],
    category: str | None = None,
) -> dict[str, list[RecommendedCard]]:
    """Extract card lists by category.

    If category is None, returns all categories as a dict.
    If category is specified, returns just that one (still as a dict for
    consistency).

    Known category tags:
        "creatures", "instants", "sorceries", "utilityartifacts",
        "enchantments", "planeswalkers", "utilitylands",
        "manaartifacts", "lands"
    """
    cardlists = data.get("container", {}).get("json_dict", {}).get("cardlists", [])
    result: dict[str, list[RecommendedCard]] = {}
    for cl in cardlists:
        tag = cl.get("tag", "")
        if category is not None and tag != category:
            continue
        result[tag] = [_card_from_view(cv, tag) for cv in cl.get("cardviews", [])]
    return result


def all_recommended_cards(data: dict[str, Any]) -> list[RecommendedCard]:
    """Return every recommended card across all categories.

    Deduplicates by name, keeping the highest-scoring entry, and sorts by
    lift descending (legacy synergy for pre-lift cache entries).
    """
    seen: dict[str, RecommendedCard] = {}
    for cards in cards_by_category(data).values():
        for card in cards:
            existing = seen.get(card.name)
            if existing is None or card.rank_key > existing.rank_key:
                seen[card.name] = card
    # Also include the meta-lists (high lift, top cards, etc.)
    for getter in (high_lift_cards, top_cards, game_changers, new_cards):
        for card in getter(data):
            existing = seen.get(card.name)
            if existing is None or card.rank_key > existing.rank_key:
                seen[card.name] = card
    return sorted(seen.values(), key=lambda c: c.rank_key, reverse=True)


def combos(data: dict[str, Any]) -> list[Combo]:
    """Extract top combos from EDHREC commander data.

    Returns a list of Combo(description, href).  The last entry is often
    a "See More..." link to the full combos page.
    """
    raw = data.get("panels", {}).get("combocounts", [])
    return [
        Combo(
            description=entry.get("value", ""),
            href=entry.get("href", ""),
        )
        for entry in raw
        if entry.get("value") != "See More..."
    ]


def combos_url(data: dict[str, Any]) -> str | None:
    """Return the URL to the full combos page, if available."""
    raw = data.get("panels", {}).get("combocounts", [])
    for entry in raw:
        if entry.get("value") == "See More...":
            href = entry.get("href", "")
            if href:
                return f"https://edhrec.com{href}"
    return None


def tags(data: dict[str, Any]) -> list[TagInfo]:
    """Extract deck theme/archetype tags with their deck counts.

    Returns sorted by count descending (most popular themes first).
    """
    raw = data.get("panels", {}).get("taglinks", [])
    result = [
        TagInfo(
            name=entry.get("value", ""),
            slug=entry.get("slug", ""),
            deck_count=entry.get("count", 0),
        )
        for entry in raw
    ]
    return sorted(result, key=lambda t: t.deck_count, reverse=True)


def num_decks(data: dict[str, Any]) -> int:
    """Return the total number of decks sampled for this commander.

    Lift-era payloads dropped ``num_decks_avg``; the commander's own
    ``container.json_dict.card.num_decks`` carries the same count.
    """
    if "num_decks_avg" in data:
        return int(data["num_decks_avg"])
    card = data.get("container", {}).get("json_dict", {}).get("card", {})
    return int(card.get("num_decks", 0))


def commander_display_name(data: dict[str, Any], fallback: str = "") -> str:
    """Return EDHREC's commander header without the trailing ``(Commander)`` suffix.

    EDHREC's ``header`` field is e.g. ``"Greasefang, Okiba Boss (Commander)"``
    or ``"Atraxa, Praetors' Voice (Budget)"`` for variant pages. Agents and
    decklist tooling want the bare canonical card name, so we strip a single
    trailing parenthetical. Mirrors the normalisation already done by
    :func:`_upsert_commander` when storing the row's ``name`` column.
    """
    raw = data.get("header", fallback) or fallback
    return re.sub(r"\s*\([^)]*\)\s*$", "", raw).strip()
