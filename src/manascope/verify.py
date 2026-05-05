"""Decklist-against-collection ownership verification.

Provides a single ``verify_decklist`` entry point used by both the CLI
``verify`` command and the ``pipeline`` subcommand. Pure data in,
pure data out — no printing or sys.exit side effects so it composes
cleanly with other workflows.
"""

from __future__ import annotations

import sqlite3

from manascope.collection import BASIC_LANDS, RARITY_ORDER, lookup_rarity
from manascope.deck import CardIdentifier


def _is_owned(name: str, owned: set[str]) -> bool:
    """Return True if *name* (or its DFC front face) appears in *owned*."""
    low = name.lower()
    # Normalise the legacy single-slash DFC separator that some exports use.
    normalised = low.replace(" / ", " // ")
    if normalised in owned:
        return True
    front = normalised.split(" // ", 1)[0] if " // " in normalised else low
    return front in owned


def verify_decklist(
    entries: list[tuple[int, CardIdentifier]],
    owned: set[str],
    cache_conn: sqlite3.Connection | None = None,
) -> dict:
    """Cross-check a parsed decklist against an owned-cards set.

    Parameters
    ----------
    entries
        Output of :func:`manascope.deck.parse_decklist`.
    owned
        Set of lower-cased card names (and DFC front faces) the user owns.
        Typically built via :func:`manascope.collection.load_collection_names`.
    cache_conn
        Optional Scryfall cache connection used to resolve missing cards'
        rarities. When omitted, every missing card is reported with
        ``rarity='unknown'``.

    Returns
    -------
    A dict with ``checked`` (count of non-basic cards examined),
    ``owned_count``, ``missing_count``, ``missing`` (sorted list of
    ``{"name", "rarity"}`` dicts), and ``by_rarity`` (the same names
    grouped by rarity for quick wildcard accounting). Basics are always
    treated as owned.
    """
    non_basic: list[str] = []
    missing: list[str] = []

    for _, ident in entries:
        if ident.name.lower() in BASIC_LANDS:
            continue
        non_basic.append(ident.name)
        if not _is_owned(ident.name, owned):
            missing.append(ident.name)

    rarities: dict[str, str] = {}
    for name in missing:
        rarities[name] = lookup_rarity(cache_conn, name) if cache_conn is not None else "unknown"

    by_rarity: dict[str, list[str]] = {}
    for name, r in rarities.items():
        by_rarity.setdefault(r, []).append(name)
    for bucket in by_rarity.values():
        bucket.sort()

    # Order the rarity dict for stable output: known rarities in canonical
    # order first, then any unrecognised rarities alphabetically.
    ordered: dict[str, list[str]] = {}
    for r in RARITY_ORDER:
        if r in by_rarity:
            ordered[r] = by_rarity[r]
    for r in sorted(by_rarity):
        if r not in ordered:
            ordered[r] = by_rarity[r]

    return {
        "checked": len(non_basic),
        "owned_count": len(owned),
        "missing_count": len(missing),
        "missing": [{"name": n, "rarity": rarities[n]} for n in sorted(missing)],
        "by_rarity": ordered,
    }
