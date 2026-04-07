"""Card display and formatting helpers.

Provides human-readable and JSON output formatters for Scryfall card data,
including land speed labels, mana rock equivalence, and notable creature
types. Used primarily by the CLI ``lookup`` command but designed as
general-purpose utilities for any module that needs card presentation.
"""

from manascope.collection import BASIC_LANDS
from manascope.deck import (
    card_subtypes,
    is_creature,
    is_land,
    is_mana_creature,
    is_mana_rock,
    land_speed,
    mana_cost,
    oracle_text,
    produced_mana,
    rock_land_equiv,
    type_line,
)

# Human-friendly land-speed labels (deck.land_speed returns short keys)
_SPEED_LABELS: dict[str, str] = {
    "untapped": "untapped",
    "shock": "shock (pay 2 life to enter untapped)",
    "conditional": "conditional",
    "tapped": "always tapped",
}

# Types frequently relevant for cheat-into-play, reanimation, or tribal synergy.
# This is a display hint - not tied to any specific commander.
_NOTABLE_TYPES: set[str] = {
    "angel",
    "demon",
    "dragon",
    "eldrazi",
    "sphinx",
    "dinosaur",
    "vampire",
    "zombie",
}


def _card_to_json(card: dict) -> dict:
    """Build a compact, agent-friendly dict from a Scryfall card."""
    d: dict = {
        "name": card.get("name", "Unknown"),
        "type_line": type_line(card),
        "mana_cost": _mana_cost_display(card),
        "cmc": card.get("cmc", 0),
        "colors": card.get("colors") or [],
        "color_identity": card.get("color_identity") or [],
        "oracle_text": oracle_text(card),
        "rarity": card.get("rarity", "unknown"),
        "set": card.get("set", "?").upper(),
        "collector_number": card.get("collector_number", "?"),
    }

    if card.get("power"):
        d["power"] = card["power"]
        d["toughness"] = card["toughness"]
    if card.get("loyalty"):
        d["loyalty"] = card["loyalty"]

    subs = card_subtypes(card)
    if subs:
        d["subtypes"] = sorted(subs)

    if is_land(card):
        d["produced_mana"] = sorted(produced_mana(card))
        d["land_speed"] = land_speed(card)

    if is_creature(card):
        hits = subs & _NOTABLE_TYPES
        if hits:
            d["notable_types"] = sorted(t.title() for t in hits)

    if is_mana_rock(card) or is_mana_creature(card):
        d["land_equiv"] = round(rock_land_equiv(card), 2)

    if card.get("legalities"):
        d["legalities"] = {
            k: v
            for k, v in card["legalities"].items()
            if k in ("commander", "brawl", "standardbrawl", "historic", "timeless")
        }

    return d


def _mana_cost_display(card: dict) -> str:
    """Format mana cost for display, handling DFCs."""
    return mana_cost(card) or "(none)"


def _produced_mana_display(card: dict) -> str:
    """Format produced mana symbols for display."""
    pm = produced_mana(card)
    if pm:
        return "  ".join("{" + c + "}" for c in sorted(pm))
    return "-"


def _land_type_note(card: dict) -> str:
    """Return basic land subtypes for fetchland/check-land context."""
    if not is_land(card):
        return ""
    hits = card_subtypes(card) & BASIC_LANDS
    return ", ".join(t.title() for t in sorted(hits)) if hits else ""


def _speed_label(card: dict) -> str:
    """Human-friendly land entry speed label."""
    raw = land_speed(card)
    return _SPEED_LABELS.get(raw, raw)


def _rock_equiv_label(card: dict) -> str:
    """Human-friendly land-equivalent value for mana rocks/creatures."""
    if is_land(card):
        return ""
    if not (is_mana_rock(card) or is_mana_creature(card)):
        return ""

    equiv = rock_land_equiv(card)
    if is_mana_creature(card):
        return f"{equiv:.1f}  (mana creature - fragile)"

    cmc = card.get("cmc", 0)
    if cmc <= 1 and equiv >= 1.0:
        return f"{equiv:.1f}  (0-1 CMC, produces 2+ mana - strong land substitute)"
    if cmc <= 2:
        return f"{equiv:.1f}  (2 CMC, produces 1 mana - reliable early ramp)"
    if cmc <= 3:
        return f"{equiv:.1f}  (3 CMC - moderate early-game value)"
    return f"{equiv:.1f}  (4+ CMC or conditional - no early-game credit)"


def _notable_creature_types(card: dict) -> str:
    """Flag creature types commonly relevant to cheat-into-play or tribal commanders."""
    if not is_creature(card):
        return ""
    subs = card_subtypes(card)
    if "changeling" in subs:
        return "Changeling (every creature type)"
    hits = subs & _NOTABLE_TYPES
    if hits:
        return ", ".join(t.title() for t in sorted(hits))
    return ""


def _display_card(card: dict, *, brief: bool = False) -> None:
    """Print a detailed card summary to stdout."""
    sep = "-" * 72
    name = card.get("name", "Unknown")
    type_line_str = type_line(card)
    rarity = card.get("rarity", "?").title()
    set_code = card.get("set", "?").upper()
    cn = card.get("collector_number", "?")
    cmc = card.get("cmc", "?")
    colors = ", ".join(card.get("colors") or ["Colorless"])
    ci = ", ".join(card.get("color_identity") or ["Colorless"])

    print()
    print(sep)
    print(f"  {name}")
    print(sep)
    print(f"  Type       : {type_line_str}")
    print(f"  Mana cost  : {_mana_cost_display(card)}")
    print(f"  CMC        : {cmc}")
    print(f"  Colours    : {colors}")
    print(f"  Identity   : {ci}")
    if not brief:
        print(f"  Rarity     : {rarity}  ({set_code} #{cn})")
        print(f"  Price      : ${card.get('prices', {}).get('usd') or '-'}")
    print()

    # Oracle text
    oracle = oracle_text(card)
    if oracle:
        print("  Oracle text:")
        for line in oracle.splitlines():
            print(f"    {line}")
        print()

    # Power / toughness / loyalty
    if card.get("power"):
        print(f"  Power / Toughness : {card['power']} / {card['toughness']}")
        print()
    if card.get("loyalty"):
        print(f"  Loyalty : {card['loyalty']}")
        print()

    # Land-specific fields
    if is_land(card):
        print(f"  Produces       : {_produced_mana_display(card)}")
        basic_types = _land_type_note(card)
        speed = _speed_label(card)
        print(f"  Basic types    : {basic_types or 'none'}")
        print(f"  Entry speed    : {speed}")
        print()
        print("  Deck interaction notes:")
        if basic_types and basic_types != "none":
            print(
                f"    * Has basic land type(s) [{basic_types}] - satisfies check lands, "
                f"verge lands, and can be fetched."
            )
        else:
            print(
                "    * No basic land type - does NOT satisfy check/verge land conditions "
                "and cannot be found by fetch lands."
            )
        if "always tapped" in speed:
            print("    * Always enters tapped - costs you a tempo every time it is played.")
        elif "shock" in speed:
            print("    * Shock land - enters untapped at the cost of 2 life; very strong.")
        elif "conditional" in speed:
            print("    * Conditional land - may enter untapped depending on board state.")
        else:
            print("    * Reliably enters untapped - no downside.")
        print()

    # Notable creature types
    notable = _notable_creature_types(card)
    if notable:
        print(f"  Notable types : {notable}")
        print()

    # Mana rock / creature land-equivalent value
    rock = _rock_equiv_label(card)
    if rock:
        print(f"  Land equivalent   : {rock}")
        print()

    # Subtypes (always shown if present)
    subs = card_subtypes(card)
    if subs:
        print(f"  Subtypes   : {', '.join(sorted(t.title() for t in subs))}")
        print()

    print(sep)
    print()
