"""SQLite-backed cache and fetch layer for Scryfall card data.

Cache key: (set_code, collector_number), both lowercase; a secondary
case-insensitive name index supports ad-hoc and fuzzy lookups.

Lookup paths:
  1. By (set_code, collector_number) — deck analysis
  2. By canonical name — ad-hoc / fuzzy queries
  3. Batch by identifier list — bulk loading via /cards/collection

All cache misses are fetched from Scryfall and stored transparently.
``deck.py`` produces the ``CardIdentifier`` tuples consumed here.
"""

import json
import sqlite3
import sys
import time
from pathlib import Path

import requests

from manascope import DB_PATH, MAX_RESPONSE_BYTES
from manascope.deck import CardIdentifier, mana_cost

# Constants

COLLECTION_URL = "https://api.scryfall.com/cards/collection"
NAMED_URL = "https://api.scryfall.com/cards/named"
BATCH_SIZE = 75  # Scryfall maximum per /cards/collection request
BATCH_DELAY = (
    0.3  # 300 ms between requests (matches EDHREC delay; well within Scryfall's guidelines)
)

USER_AGENT = "manascope/0.1 (personal deckbuilding helper; non-commercial)"
ACCEPT = "application/json"

# Schema

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    set_code         TEXT NOT NULL,
    collector_number TEXT NOT NULL,
    name             TEXT NOT NULL,
    mana_cost        TEXT NOT NULL DEFAULT '',
    full_json        TEXT NOT NULL,
    fetched_at       TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (set_code, collector_number)
);

CREATE INDEX IF NOT EXISTS idx_cards_name
    ON cards (name COLLATE NOCASE);
"""

# Connection / schema helpers


def open_cache(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Open (or create) the SQLite cache and ensure the schema is up to date.

    Safe to call multiple times - CREATE TABLE/INDEX IF NOT EXISTS is idempotent.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


# Internal helpers


def _upsert_cards(conn: sqlite3.Connection, cards: list[dict]) -> None:
    """Upsert a list of raw Scryfall card objects into the cache."""
    for card in cards:
        set_code = card.get("set", "").lower()
        collector_number = card.get("collector_number", "").lower()
        name = card.get("name", "")
        cost = mana_cost(card)
        full_json = json.dumps(card)
        conn.execute(
            """
            INSERT INTO cards (set_code, collector_number, name, mana_cost, full_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(set_code, collector_number) DO UPDATE SET
                name       = excluded.name,
                mana_cost  = excluded.mana_cost,
                full_json  = excluded.full_json,
                fetched_at = datetime('now')
            """,
            (set_code, collector_number, name, cost, full_json),
        )
    conn.commit()


def _make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": ACCEPT})
    return session


def _escape_like(value: str) -> str:
    """Escape SQL LIKE wildcards so *value* is matched literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# Public read API


def get_card_by_id(
    conn: sqlite3.Connection,
    set_code: str,
    collector_number: str,
) -> dict | None:
    """Return the full Scryfall card dict for a given (set, collector_number).

    Returns None if not in the cache. Does NOT fetch from the network.
    """
    row = conn.execute(
        "SELECT full_json FROM cards WHERE set_code = ? AND collector_number = ?",
        (set_code.lower(), collector_number.lower()),
    ).fetchone()
    return json.loads(row[0]) if row else None


def get_card_by_name(
    conn: sqlite3.Connection,
    name: str,
) -> dict | None:
    """Return the full Scryfall card dict for a given canonical name.

    Case-insensitive.  Also finds double-faced cards stored as
    ``"Front // Back"`` when queried with just ``"Front"``.

    Returns None if not in the cache.  Does NOT fetch from the network.
    """
    row = conn.execute(
        "SELECT full_json FROM cards WHERE name = ? COLLATE NOCASE "
        "ORDER BY fetched_at DESC LIMIT 1",
        (name,),
    ).fetchone()
    if row is None:
        # DFC front-face fallback: "Sheoldred" → "Sheoldred // The True Scriptures"
        row = conn.execute(
            "SELECT full_json FROM cards WHERE name LIKE ? ESCAPE '\\' COLLATE NOCASE "
            "ORDER BY fetched_at DESC LIMIT 1",
            (_escape_like(name) + " // %",),
        ).fetchone()
    return json.loads(row[0]) if row else None


def get_all_cards(conn: sqlite3.Connection) -> list[dict]:
    """Return every card in the cache as a list of full Scryfall card dicts."""
    rows = conn.execute("SELECT full_json FROM cards").fetchall()
    return [json.loads(r[0]) for r in rows]


# Public fetch API  (cache-first; network only for misses)


def fetch_cards_by_id(
    conn: sqlite3.Connection,
    identifiers: list[CardIdentifier],
    *,
    force_refresh: bool = False,
) -> dict[tuple[str, str], dict]:
    """Return a dict of (set_code, collector_number) -> full card dict.

    Maps for every identifier supplied.

    Cache-first: only cards not already cached are fetched from Scryfall.
    Set force_refresh=True to bypass the cache and re-fetch everything.

    Cards not found on Scryfall are logged to stderr and omitted from the result.
    """
    result: dict[tuple[str, str], dict] = {}
    missing: list[CardIdentifier] = []

    if force_refresh:
        missing = list(identifiers)
    else:
        for ident in identifiers:
            key = (ident.set_code.lower(), ident.collector_number.lower())
            card = get_card_by_id(conn, ident.set_code, ident.collector_number)
            if card is not None:
                result[key] = card
            else:
                missing.append(ident)

    if not missing:
        return result

    # Fetch missing cards in batches from Scryfall /cards/collection
    session = _make_session()
    chunks = [missing[i : i + BATCH_SIZE] for i in range(0, len(missing), BATCH_SIZE)]

    for batch_idx, chunk in enumerate(chunks, 1):
        scryfall_ids = [
            {"set": i.set_code.lower(), "collector_number": i.collector_number} for i in chunk
        ]
        print(
            f"  [scryfall] batch {batch_idx}/{len(chunks)}: "
            f"fetching {len(scryfall_ids)} card(s)...",
            file=sys.stderr,
        )

        try:
            resp = session.post(
                COLLECTION_URL,
                json={"identifiers": scryfall_ids},
                timeout=30,
            )
            resp.raise_for_status()
            if len(resp.content) > MAX_RESPONSE_BYTES:
                print(
                    f"  [scryfall] ERROR: response too large ({len(resp.content)} bytes), skipping.",
                    file=sys.stderr,
                )
                if batch_idx < len(chunks):
                    time.sleep(BATCH_DELAY)
                continue
            body = resp.json()
        except requests.RequestException as exc:
            print(f"  [scryfall] ERROR batch {batch_idx}: {exc}", file=sys.stderr)
            if batch_idx < len(chunks):
                time.sleep(BATCH_DELAY)
            continue

        fetched: list[dict] = body.get("data", [])
        _upsert_cards(conn, fetched)

        for card in fetched:
            key = (card["set"].lower(), card["collector_number"].lower())
            result[key] = card

        for nf in body.get("not_found", []):
            print(
                f"  [scryfall] WARNING not found - "
                f"set={nf.get('set')!r} number={nf.get('collector_number')!r}",
                file=sys.stderr,
            )

        if batch_idx < len(chunks):
            time.sleep(BATCH_DELAY)

    return result


def fetch_card_by_name(
    conn: sqlite3.Connection,
    name: str,
    *,
    fuzzy: bool = True,
    force_refresh: bool = False,
) -> dict | None:
    """Return the full Scryfall card dict for a card looked up by name.

    Cache-first: if any printing of this card is already cached, return it
    without hitting the network.  Set force_refresh=True to re-fetch.

    Uses Scryfall's /cards/named endpoint (fuzzy by default so minor typos
    are tolerated).  The result is stored in the cache under its canonical
    (set, collector_number) key before being returned.

    Returns None if Scryfall cannot find the card.
    """
    if not force_refresh:
        cached = get_card_by_name(conn, name)
        if cached is not None:
            return cached

    session = _make_session()
    param_key = "fuzzy" if fuzzy else "exact"
    print(f"  [scryfall] fetching by name: {name!r}...", file=sys.stderr)

    try:
        resp = session.get(
            NAMED_URL,
            params={param_key: name},
            timeout=30,
        )
        if resp.status_code == 404:
            print(
                f"  [scryfall] WARNING: card not found by name - {name!r}",
                file=sys.stderr,
            )
            time.sleep(BATCH_DELAY)
            return None
        resp.raise_for_status()
        if len(resp.content) > MAX_RESPONSE_BYTES:
            print(
                f"  [scryfall] ERROR: response too large ({len(resp.content)} bytes), skipping.",
                file=sys.stderr,
            )
            time.sleep(BATCH_DELAY)
            return None
        card = resp.json()
    except requests.RequestException as exc:
        print(f"  [scryfall] ERROR fetching {name!r}: {exc}", file=sys.stderr)
        return None

    time.sleep(BATCH_DELAY)

    _upsert_cards(conn, [card])
    return card


# Public fetch API  (batch by name via /cards/collection)


def fetch_cards_by_names(
    conn: sqlite3.Connection,
    names: list[str],
    *,
    force_refresh: bool = False,
) -> dict[str, dict]:
    """Return a dict of requested_name -> full card dict for every name supplied.

    Keys in the returned dict correspond to the input *names* (preserving
    the caller's spelling), so look-ups like ``name in result`` always work
    even when the canonical Scryfall name differs (e.g. double-faced cards).

    Cache-first: only names not already cached are fetched from Scryfall's
    ``/cards/collection`` endpoint using ``{"name": ...}`` identifiers,
    batched in groups of up to 75 (Scryfall's maximum).

    This is much faster than calling ``fetch_card_by_name`` in a loop
    because it issues one HTTP request per 75 cards instead of one per card.

    Cards not found on Scryfall are logged to stderr and omitted from the
    result.  The ``force_refresh`` flag bypasses the cache for all names.
    """
    result: dict[str, dict] = {}
    missing: list[str] = []

    if force_refresh:
        missing = list(names)
    else:
        for name in names:
            cached = get_card_by_name(conn, name)
            if cached is not None:
                result[name] = cached
            else:
                # Also check for double-faced cards stored as "Front // Back"
                row = conn.execute(
                    "SELECT full_json FROM cards WHERE LOWER(name) LIKE LOWER(?) ESCAPE '\\'",
                    (_escape_like(name) + " // %",),
                ).fetchone()
                if row:
                    card = json.loads(row[0])
                    result[name] = card
                else:
                    missing.append(name)

    if not missing:
        return result

    session = _make_session()
    chunks = [missing[i : i + BATCH_SIZE] for i in range(0, len(missing), BATCH_SIZE)]
    remaining_missing: list[str] = []

    for batch_idx, chunk in enumerate(chunks, 1):
        scryfall_ids = [{"name": n} for n in chunk]
        print(
            f"  [scryfall] batch {batch_idx}/{len(chunks)}: "
            f"fetching {len(scryfall_ids)} card(s) by name...",
            file=sys.stderr,
        )

        try:
            resp = session.post(
                COLLECTION_URL,
                json={"identifiers": scryfall_ids},
                timeout=30,
            )
            resp.raise_for_status()
            if len(resp.content) > MAX_RESPONSE_BYTES:
                print(
                    f"  [scryfall] ERROR: response too large ({len(resp.content)} bytes), skipping.",
                    file=sys.stderr,
                )
                if batch_idx < len(chunks):
                    time.sleep(BATCH_DELAY)
                continue
            body = resp.json()
        except requests.RequestException as exc:
            print(f"  [scryfall] ERROR batch {batch_idx}: {exc}", file=sys.stderr)
            if batch_idx < len(chunks):
                time.sleep(BATCH_DELAY)
            continue

        fetched: list[dict] = body.get("data", [])
        _upsert_cards(conn, fetched)

        # Match returned cards back to their requested names.
        # Build a lowercase canonical→requested map for this chunk.
        req_by_lower = {n.lower(): n for n in chunk}
        for card in fetched:
            canonical = card["name"]
            # Try exact lowercase match, then front-face prefix match
            req_name = req_by_lower.get(canonical.lower())
            if req_name is None:
                # DFC: canonical is "Front // Back", requested was "Front"
                front = canonical.split(" // ")[0]
                req_name = req_by_lower.get(front.lower(), canonical)
            result[req_name] = card

        not_found_names = [nf.get("name") for nf in body.get("not_found", [])]
        remaining_missing.extend(n for n in not_found_names if n)

        if batch_idx < len(chunks):
            time.sleep(BATCH_DELAY)

    # Fallback: for cards not resolved by the batch endpoint (typically
    # double-faced / transform cards where EDHREC supplies a shortened
    # name), try individual fuzzy lookup via /cards/named.
    if remaining_missing:
        print(
            f"  [scryfall] {len(remaining_missing)} card(s) not found in batch, "
            f"trying fuzzy fallback...",
            file=sys.stderr,
        )
        for i, name in enumerate(remaining_missing):
            if i > 0:
                time.sleep(BATCH_DELAY)
            card = fetch_card_by_name(conn, name, fuzzy=True)
            if card is not None:
                result[name] = card
            else:
                print(
                    f"  [scryfall] WARNING not found - name={name!r}",
                    file=sys.stderr,
                )

    return result


# Convenience: bulk load all cards for a decklist at once


def load_decklist_cards(
    conn: sqlite3.Connection,
    identifiers: list[CardIdentifier],
    *,
    force_refresh: bool = False,
    verbose: bool = True,
) -> dict[tuple[str, str], dict]:
    """Ensure every card in a decklist is in the cache and return a complete mapping.

    Returns a (set_code_lower, collector_number_lower) -> card dict mapping.

    This is the primary entry point for tools that need the full card data
    for every card in the deck.  It prints a summary of cache hits vs
    network fetches when verbose=True.
    """
    result = fetch_cards_by_id(conn, identifiers, force_refresh=force_refresh)
    if verbose:
        n_total = len(identifiers)
        n_fetched = len(result)
        n_missing = n_total - n_fetched
        print(f"Cache: {n_fetched}/{n_total} card(s) loaded, {n_missing} not found.")
    return result
