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
