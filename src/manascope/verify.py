"""Decklist-against-collection ownership verification.

Provides a single ``verify_decklist`` entry point used by both the CLI
``verify`` command and the ``pipeline`` subcommand. Pure data in,
pure data out — no printing or sys.exit side effects so it composes
cleanly with other workflows.
"""

from __future__ import annotations

import sqlite3

from manascope.collection import (
    BASIC_LANDS,
    RARITY_ORDER,
    PrintingKey,
    lookup_rarity,
)
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


def _is_owned_printing(ident: CardIdentifier, owned_printings: set[PrintingKey]) -> bool:
    """Return True if the exact (name, set, cn) printing is in the set.

    DFC names are matched on the front face since collection exports may
    list either the full or the truncated name.
    """
    name_low = ident.name.lower().replace(" / ", " // ")
    set_low = ident.set_code.lower()
    cn_low = ident.collector_number.strip().lower()

    if (name_low, set_low, cn_low) in owned_printings:
        return True
    if " // " in name_low:
        front = name_low.split(" // ", 1)[0]
        if (front, set_low, cn_low) in owned_printings:
            return True
    return False


def verify_decklist(
    entries: list[tuple[int, CardIdentifier]],
    owned: set[str],
    cache_conn: sqlite3.Connection | None = None,
    *,
    owned_printings: set[PrintingKey] | None = None,
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
    owned_printings
        Optional set of ``(name_lower, set_lower, cn_lower)`` tuples from
        :func:`manascope.collection.load_collection_printings`. When provided,
        each decklist line whose printing is *not* in the set is reported
        under ``wrong_printing`` (in addition to the existing name-based
        ``missing`` check). Cards whose names aren't owned at all stay in
        ``missing``; cards whose names are owned but at a different printing
        appear only in ``wrong_printing``. When ``None`` (the default),
        printing-level checking is skipped entirely — backward compatible
        with collections that don't carry printing data (MTGA exports).

    Returns
    -------
    A dict with ``checked`` (count of non-basic cards examined),
    ``owned_count``, ``missing_count``, ``missing`` (sorted list of
    ``{"name", "rarity"}`` dicts), ``by_rarity`` (the same names grouped
    by rarity for quick wildcard accounting), and — when
    ``owned_printings`` is supplied — ``wrong_printing_count`` plus a
    sorted ``wrong_printing`` list of ``{"name", "set", "collector_number"}``
    dicts for cards whose printing is not in the collection.
    """
    non_basic: list[str] = []
    missing: list[str] = []
    wrong_printing: list[dict[str, str]] = []

    # Local alias gives the type checker a non-Optional reference to use
    # inside the loop without repeated narrowing.
    printings_check: set[PrintingKey] | None = owned_printings
    check_printings = printings_check is not None

    for _, ident in entries:
        if ident.name.lower() in BASIC_LANDS:
            continue
        non_basic.append(ident.name)
        name_owned = _is_owned(ident.name, owned)
        if not name_owned:
            missing.append(ident.name)
            continue
        # Name is owned. If we're checking printings, also verify the exact
        # (set, collector#) tuple matches an owned non-foil printing.
        if printings_check is not None and not _is_owned_printing(ident, printings_check):
            wrong_printing.append(
                {
                    "name": ident.name,
                    "set": ident.set_code,
                    "collector_number": ident.collector_number,
                }
            )

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

    result: dict = {
        "checked": len(non_basic),
        "owned_count": len(owned),
        "missing_count": len(missing),
        "missing": [{"name": n, "rarity": rarities[n]} for n in sorted(missing)],
        "by_rarity": ordered,
    }
    if check_printings:
        wrong_printing.sort(key=lambda d: (d["name"], d["set"], d["collector_number"]))
        result["wrong_printing_count"] = len(wrong_printing)
        result["wrong_printing"] = wrong_printing
    return result
