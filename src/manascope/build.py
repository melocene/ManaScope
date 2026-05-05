"""Draft a deck from a commander + collection using EDHREC recommendations.

The :func:`run` entry point walks the standard "build a deck from scratch"
flow that AGENTS.md documents:

1. Resolve the commander from the Scryfall cache (its color identity drives
   every downstream filter).
2. Load EDHREC's recommended cards for that commander from the local cache
   (no network calls; ``manascope prime`` must have been run first).
3. Cross-reference EDHREC ∩ collection ∩ format-legal ∩ colour-identity
   to pick the spell slate.
4. Fill the remaining slots with basic lands distributed by pip count.

The output is a complete decklist text in the format expected by
:mod:`manascope.deck` (``Commander``/``Deck`` headers for brawl/standardbrawl,
plain list for paper Commander). With ``json_flag=True`` the same data is
emitted as a structured report instead so agents can post-process without
re-parsing the text.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from manascope import DB_PATH
from manascope import edhrec as ec
from manascope import scryfall as sc
from manascope.collection import BASIC_LANDS, load_collection, load_collections
from manascope.deck import (
    FORMAT_DECK_SIZE as _DECK_SIZE,
)
from manascope.deck import (
    WUBRG_ORDER,
    is_legal,
    pip_colours,
)

# Format → (deck_size, default_lands). Deck size is shared with deck.py;
# default land counts live here because they're a build-tool concern only.
_DEFAULT_LANDS: dict[str, int] = {
    "commander": 36,
    "brawl": 35,
    "standardbrawl": 24,
}
FORMAT_DECK_SIZE: dict[str, tuple[int, int]] = {
    fmt: (_DECK_SIZE[fmt], _DEFAULT_LANDS[fmt]) for fmt in _DECK_SIZE
}

# Colour → basic land name
BASIC_FOR_COLOUR: dict[str, str] = {
    "W": "Plains",
    "U": "Island",
    "B": "Swamp",
    "R": "Mountain",
    "G": "Forest",
}


def _format_line(card: dict, qty: int = 1) -> str:
    """Render a Scryfall card dict as a decklist line.

    Uses ``(set) collector_number`` with the printing stored in the cache.
    """
    set_code = card.get("set", "").upper()
    cn = card.get("collector_number", "1")
    name = card.get("name", "")
    # Front-face only for DFCs/Adventures (per Brawl decklist rules);
    # paper Commander allows full names but the front face is also accepted.
    if " // " in name:
        name = name.split(" // ", 1)[0]
    return f"{qty} {name} ({set_code}) {cn}"


def _basic_distribution(
    pip_counts: Counter[str],
    colours: list[str],
    total: int,
) -> dict[str, int]:
    """Distribute *total* basic land slots across *colours* by pip share.

    Largest-remainder method so the counts sum exactly to *total*. Falls
    back to even split when the deck has zero coloured pips (mono-colourless
    or pre-spell builds).
    """
    if total <= 0 or not colours:
        return {c: 0 for c in colours}

    pip_total = sum(pip_counts[c] for c in colours)
    if pip_total == 0:
        share = total // len(colours)
        rem = total - share * len(colours)
        result = {c: share for c in colours}
        for c in colours[:rem]:
            result[c] += 1
        return result

    raw = {c: pip_counts[c] / pip_total * total for c in colours}
    floored = {c: int(v) for c, v in raw.items()}
    shortfall = total - sum(floored.values())
    for c in sorted(colours, key=lambda k: raw[k] - floored[k], reverse=True):
        if shortfall <= 0:
            break
        floored[c] += 1
        shortfall -= 1
    return floored


def _is_basic_land(card: dict) -> bool:
    """True for basic lands (which a build never adds via EDHREC slots)."""
    return card.get("name", "").lower() in BASIC_LANDS


def _is_land(card: dict) -> bool:
    return "land" in card.get("type_line", "").lower()


def select_spells(
    commander_card: dict,
    edhrec_data: dict,
    owned: dict[str, dict],
    conn: Any,
    *,
    fmt: str,
    target_count: int,
    top: int,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (selected, candidates_unowned, gaps_not_cached).

    *selected* is the list of card dicts chosen for the deck (size ≤
    target_count, sorted by EDHREC synergy descending). *candidates_unowned*
    are EDHREC picks that pass legality + identity but the user does not
    own (useful for a wishlist). *gaps_not_cached* are EDHREC picks that
    couldn't be evaluated because their Scryfall data isn't cached.
    """
    cmd_ci: set[str] = set(commander_card.get("color_identity", []))
    cmd_name_lc = commander_card.get("name", "").lower()

    selected: list[dict] = []
    selected_names: set[str] = set()
    unowned: list[dict] = []
    not_cached: list[dict] = []

    for sc_card in ec.all_recommended_cards(edhrec_data)[:top]:
        # Skip the commander itself in case EDHREC echoes it back.
        if sc_card.name.lower() == cmd_name_lc:
            continue

        cj = sc.get_card_by_name(conn, sc_card.name)
        if cj is None:
            not_cached.append({"name": sc_card.name, "synergy": sc_card.synergy_pct})
            continue

        if not is_legal(cj, fmt):
            continue
        # Stay within commander colour identity.
        if not set(cj.get("color_identity", [])).issubset(cmd_ci):
            continue
        # Skip basic lands; lands are managed by the basic-distribution step.
        if _is_basic_land(cj):
            continue

        canonical = cj.get("name", sc_card.name)
        if canonical.lower() in selected_names:
            continue

        if canonical.lower() in owned:
            if len(selected) < target_count:
                cj_with_syn = dict(cj)
                cj_with_syn["_synergy"] = sc_card.synergy_pct
                selected.append(cj_with_syn)
                selected_names.add(canonical.lower())
        else:
            unowned.append(
                {
                    "name": canonical,
                    "synergy": sc_card.synergy_pct,
                    "rarity": cj.get("rarity", "unknown"),
                    "type_line": cj.get("type_line", ""),
                    "cmc": cj.get("cmc", 0),
                }
            )

    return selected, unowned, not_cached


def build_decklist_text(
    commander_card: dict,
    selected_spells: list[dict],
    basics: dict[str, int],
    *,
    fmt: str,
) -> str:
    """Render the final decklist as text in the canonical decklist format."""
    lines: list[str] = []
    use_headers = fmt in {"brawl", "standardbrawl"}

    if use_headers:
        lines.append("Commander")
    lines.append(_format_line(commander_card))
    if use_headers:
        lines.append("")
        lines.append("Deck")

    for card in selected_spells:
        lines.append(_format_line(card))

    # Basics: emit one consolidated line per colour (e.g. ``8 Plains (FDN) 1``)
    # so the file matches the canonical hand-edited form and Arena's importer
    # collapses duplicates anyway. The commander's set is a fallback printing —
    # any basic printing imports correctly.
    set_code = commander_card.get("set", "").upper() or "FDN"
    for colour in WUBRG_ORDER:
        qty = basics.get(colour, 0)
        if qty <= 0:
            continue
        basic_name = BASIC_FOR_COLOUR[colour]
        lines.append(f"{qty} {basic_name} ({set_code}) 1")

    return "\n".join(lines) + "\n"


def run(
    *,
    commander_name: str,
    collection_paths: list[Path],
    fmt: str = "brawl",
    top: int = 80,
    lands: int | None = None,
    output: Path | None = None,
    json_flag: bool = False,
    cache: Path = DB_PATH,
) -> None:
    """Entry point invoked by ``manascope build``."""
    if fmt not in FORMAT_DECK_SIZE:
        raise ValueError(f"unknown format {fmt!r}; expected one of {sorted(FORMAT_DECK_SIZE)}")
    deck_size, default_lands = FORMAT_DECK_SIZE[fmt]
    land_count = lands if lands is not None else default_lands
    spell_target = deck_size - 1 - land_count  # -1 for commander
    if spell_target <= 0:
        raise ValueError(
            f"land_count {land_count} leaves no room for spells in a {deck_size}-card deck"
        )

    owned = (
        load_collections(collection_paths)
        if len(collection_paths) > 1
        else load_collection(collection_paths[0])
    )

    conn = sc.open_cache(cache)
    try:
        commander_card = sc.get_card_by_name(conn, commander_name)
        if commander_card is None:
            raise ValueError(
                f"commander {commander_name!r} not in Scryfall cache. "
                f"Run: uv run manascope lookup {commander_name!r}"
            )
        if not commander_card.get("type_line", "").lower().startswith("legendary"):
            # EDHREC commanders must be legendary; surface the issue
            # rather than silently producing an illegal deck.
            print(
                f"WARNING: {commander_card.get('name')} is not Legendary; "
                "EDHREC data may be missing.",
                file=sys.stderr,
            )

        edhrec_data = ec.fetch_commander(conn, commander_card.get("name", commander_name))
        if edhrec_data is None:
            raise ValueError(
                f"no EDHREC data cached for {commander_name!r}. "
                f'Run: uv run manascope prime "{commander_name}"'
            )

        selected, unowned, not_cached = select_spells(
            commander_card,
            edhrec_data,
            owned,
            conn,
            fmt=fmt,
            target_count=spell_target,
            top=top,
        )
    finally:
        conn.close()

    # Distribute basic lands across the commander's colour identity by the
    # pip totals of the selected spells.
    cmd_colours = [c for c in WUBRG_ORDER if c in set(commander_card.get("color_identity", []))]
    pip_counter: Counter[str] = Counter()
    cmd_ci_set: set[str] = set(cmd_colours)
    for card in selected:
        cost = card.get("mana_cost", "") or ""
        for sym in pip_colours(cost, cmd_ci_set):
            pip_counter[sym] += 1
    basics = _basic_distribution(pip_counter, cmd_colours or ["C"], land_count)

    text = build_decklist_text(commander_card, selected, basics, fmt=fmt)

    if json_flag:
        report = {
            "commander": {
                "name": commander_card.get("name"),
                "set": commander_card.get("set"),
                "color_identity": sorted(cmd_ci_set),
            },
            "format": fmt,
            "targets": {
                "deck_size": deck_size,
                "lands": land_count,
                "spells": spell_target,
            },
            "stats": {
                "selected": len(selected),
                "shortfall": max(0, spell_target - len(selected)),
                "unowned_candidates": len(unowned),
                "not_cached": len(not_cached),
            },
            "selected": [
                {
                    "name": c.get("name"),
                    "synergy": c.get("_synergy", 0.0),
                    "rarity": c.get("rarity"),
                    "cmc": c.get("cmc", 0),
                    "type_line": c.get("type_line", ""),
                }
                for c in selected
            ],
            "unowned_candidates": unowned,
            "not_cached": not_cached,
            "basics": basics,
            "decklist": text,
        }
        print(json.dumps(report))
    elif output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        print(
            f"Wrote {len(selected) + sum(basics.values()) + 1}-card decklist to {output} "
            f"(spells: {len(selected)}/{spell_target}, "
            f"unowned candidates: {len(unowned)}, not cached: {len(not_cached)})",
            file=sys.stderr,
        )
    else:
        print(text, end="")
        print(
            f"# spells: {len(selected)}/{spell_target}, "
            f"unowned candidates: {len(unowned)}, not cached: {len(not_cached)}",
            file=sys.stderr,
        )
