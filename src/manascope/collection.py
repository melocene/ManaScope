"""Collection loading and ownership verification for ManaBox and MTGA exports.

Handles two CSV formats: ManaBox (physical collections with Quantity column)
and MTGA (digital collections with Count column). Also supports JSON input.
Exports ``load_collection``, ``load_collection_names``, ``lookup_rarity``,
and the constants ``BASIC_LANDS`` and ``RARITY_ORDER``. Used by the CLI
verify and review commands.
"""

import csv
import json
import sqlite3
from pathlib import Path

BASIC_LANDS: set[str] = {"plains", "island", "swamp", "mountain", "forest"}

RARITY_ORDER: list[str] = ["mythic", "rare", "uncommon", "common"]


def _load_csv(path: Path) -> dict[str, dict]:
    """Parse a CSV collection and return {name_lower: entry_dict}."""
    result: dict[str, dict] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            name = row.get("Name")
            if not name:
                continue

            # Determine count column (MTGA uses Count, ManaBox uses Quantity)
            count_str = row.get("Count") or row.get("Quantity") or "1"
            try:
                count = int(count_str)
            except ValueError:
                count = 1

            if count <= 0:
                continue

            low = name.lower()
            if low not in result:
                result[low] = {"name": name, "count": count}
            else:
                result[low]["count"] += count

            if " // " in low:
                front = low.split(" // ", 1)[0]
                if front not in result:
                    result[front] = {"name": name.split(" // ")[0], "count": count}
                else:
                    result[front]["count"] += count
    return result


def _load_json(path: Path) -> dict[str, dict]:
    """Parse a JSON collection and return {name_lower: entry_dict}."""
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    result: dict[str, dict] = {}
    for entry in data.get("cards", []):
        name: str = entry.get("name", "")
        low = name.lower()
        result[low] = entry
        if " // " in low:
            front = low.split(" // ", 1)[0]
            result.setdefault(front, entry)
    return result


def load_collection(path: Path) -> dict[str, dict]:
    """Load MTGA/Physical collection → ``{name_lower: entry_dict}``.

    Double-faced card front faces are also indexed so decklist entries
    using only the front face still match.
    """
    if path.suffix.lower() == ".csv":
        return _load_csv(path)
    return _load_json(path)


def load_collection_names(path: Path) -> set[str]:
    """Load just the set of owned card names (lowercased), including DFC front faces."""
    return set(load_collection(path).keys())


def load_collections(paths: list[Path]) -> dict[str, dict]:
    """Merge collections from multiple files into one ``{name_lower: entry_dict}``.

    When the same card name appears in more than one file the ``count``
    values are summed.  If only one path is provided the call delegates
    directly to :func:`load_collection`.
    """
    if len(paths) == 1:
        return load_collection(paths[0])

    merged: dict[str, dict] = {}
    for path in paths:
        for key, entry in load_collection(path).items():
            if key in merged:
                merged[key]["count"] += entry.get("count", 1)
            else:
                merged[key] = dict(entry)
    return merged


def load_collections_names(paths: list[Path]) -> set[str]:
    """Return the set of owned card names (lowercased) across multiple collection files."""
    return set(load_collections(paths).keys())


def lookup_rarity(conn: sqlite3.Connection, card_name: str) -> str:
    """Return the rarity string for *card_name* from the Scryfall cache.

    Returns ``'unknown'`` if not cached or if cached data is malformed.
    """
    from manascope.scryfall import get_card_by_name

    try:
        card = get_card_by_name(conn, card_name)
    except json.JSONDecodeError, TypeError:
        return "unknown"
    if card is None:
        return "unknown"
    return card.get("rarity", "unknown")


def filter_collection(
    owned: dict[str, dict],
    conn: sqlite3.Connection,
    *,
    color_identity: str | None = None,
    within_identity: str | None = None,
    type_substr: str | None = None,
    rarity: str | None = None,
    cmc: int | None = None,
    cmc_max: int | None = None,
    legal_in: str | None = None,
) -> list[dict]:
    """Filter a loaded collection against Scryfall cache attributes.

    Cards not present in the Scryfall cache are silently skipped (callers
    that care can prime the cache first via ``lookup`` or ``prime``).

    Parameters
    ----------
    owned
        ``{name_lower: entry_dict}`` mapping returned by ``load_collection``.
    conn
        Open Scryfall cache connection.
    color_identity
        Exact match. Use the empty string for colourless. Pass colours in
        any order: ``"BW"`` and ``"WB"`` both match the same identity.
    within_identity
        Subset match. ``"BW"`` matches BW, B, W, and colourless cards.
        Mutually useful with EDHREC commander color identity filtering.
    type_substr
        Case-insensitive substring match against the card's ``type_line``.
    rarity
        One of ``common``/``uncommon``/``rare``/``mythic``/``special``.
    cmc
        Exact CMC match.
    cmc_max
        Maximum CMC (inclusive).
    legal_in
        Format key (``commander``/``brawl``/``standardbrawl``). Cards must
        be ``legal`` in that format. Uses :func:`manascope.deck.is_legal`
        which knows the standardbrawl alias.

    Returns
    -------
    A list of card dicts, each containing the canonical name, owned count,
    rarity, CMC, type_line, and color identity. Sorted by name.
    """
    from manascope.deck import is_legal
    from manascope.scryfall import get_card_by_name

    target_ci: set[str] | None = None
    if color_identity is not None:
        target_ci = set(color_identity.upper())
    within_ci: set[str] | None = None
    if within_identity is not None:
        within_ci = set(within_identity.upper())
    type_needle = type_substr.lower() if type_substr else None
    rarity_needle = rarity.lower() if rarity else None

    results: list[dict] = []
    seen_ids: set[int] = set()
    for entry in owned.values():
        # ``owned`` indexes DFCs under both "Front // Back" and "Front";
        # both keys point at the same dict object, so id-dedup avoids
        # double-counting without name-string parsing.
        if id(entry) in seen_ids:
            continue
        seen_ids.add(id(entry))
        name = entry.get("name", "")
        try:
            card = get_card_by_name(conn, name)
        except json.JSONDecodeError, TypeError:
            continue
        if card is None:
            continue

        card_ci = set(card.get("color_identity", []))
        if target_ci is not None and card_ci != target_ci:
            continue
        if within_ci is not None and not card_ci.issubset(within_ci):
            continue
        if type_needle and type_needle not in card.get("type_line", "").lower():
            continue
        if rarity_needle and card.get("rarity", "").lower() != rarity_needle:
            continue
        if cmc is not None and card.get("cmc", 0) != cmc:
            continue
        if cmc_max is not None and card.get("cmc", 0) > cmc_max:
            continue
        if legal_in and not is_legal(card, legal_in):
            continue

        results.append(
            {
                "name": card.get("name", name),
                "count": entry.get("count", 1),
                "rarity": card.get("rarity", "unknown"),
                "cmc": card.get("cmc", 0),
                "type_line": card.get("type_line", ""),
                "color_identity": sorted(card_ci),
                "set": card.get("set", ""),
            }
        )

    return sorted(results, key=lambda r: r["name"])
