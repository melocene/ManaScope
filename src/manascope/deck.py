"""Card data helpers, decklist parsing, land classification, and synergy extraction.

Provides the core building blocks used by analyze, review, and the CLI:

- **Card attribute accessors**: type_line, oracle_text, card_subtypes, produced_mana, etc.
- **Land classification**: land_speed (untapped/shock/conditional/tapped), is_land.
- **Mana rock evaluation**: is_mana_rock, is_mana_creature, rock_land_equiv.
- **Synergy detection**: extract_synergy_types, has_synergy_type.
- **Decklist parsing**: parse_decklist, detect_format, pip_colours, colour_balance.
"""

import re
import sys
from collections import Counter
from pathlib import Path
from typing import NamedTuple

# Constants


class CardIdentifier(NamedTuple):
    """Minimal identifier for a card as it appears in a decklist."""

    set_code: str
    collector_number: str
    name: str = ""  # optional hint, not used for cache key


# Canonical WUBRG ordering for consistent display
WUBRG_ORDER = "WUBRG"

# Full colour map for labels
COLOUR_LABELS: dict[str, str] = {
    "W": "White",
    "U": "Blue",
    "B": "Black",
    "R": "Red",
    "G": "Green",
}

# Format-specific land count targets  (low, high, human label)
FORMAT_TARGETS: dict[str, tuple[float, float, str]] = {
    "commander": (33.0, 36.0, "33-35 raw"),
    "brawl": (33.0, 36.0, "33-35 raw"),
    "standardbrawl": (20.0, 24.0, "22-24 raw"),
}

# Scryfall legality field name for each supported format
FORMAT_LEGALITY_FIELD: dict[str, str] = {
    "commander": "commander",
    "brawl": "brawl",
    "standardbrawl": "standardbrawl",
}

# Comprehensive set of MTG creature types used for synergy detection.
# This list covers every type that commonly appears in "lord" or "cheat"
# abilities.  It is intentionally broad - false positives are filtered by
# context (list/or patterns in oracle text).
CREATURE_TYPES: set[str] = {
    "advisor",
    "aetherborn",
    "alien",
    "ally",
    "angel",
    "antelope",
    "ape",
    "archer",
    "archon",
    "army",
    "artificer",
    "assassin",
    "assembly-worker",
    "atog",
    "aurochs",
    "avatar",
    "azra",
    "badger",
    "barbarian",
    "bard",
    "basilisk",
    "bat",
    "bear",
    "beast",
    "beholder",
    "berserker",
    "bird",
    "blinkmoth",
    "boar",
    "bringer",
    "brushwagg",
    "camarid",
    "camel",
    "caribou",
    "carrier",
    "cat",
    "centaur",
    "cephalid",
    "chimera",
    "citizen",
    "cleric",
    "cockatrice",
    "construct",
    "coward",
    "crab",
    "crocodile",
    "cyclops",
    "dauthi",
    "demigod",
    "demon",
    "deserter",
    "detective",
    "devil",
    "dinosaur",
    "djinn",
    "dog",
    "dragon",
    "drake",
    "dreadnought",
    "drone",
    "druid",
    "dryad",
    "dwarf",
    "efreet",
    "egg",
    "elder",
    "eldrazi",
    "elemental",
    "elephant",
    "elf",
    "elk",
    "employee",
    "eye",
    "faerie",
    "ferret",
    "fish",
    "flagbearer",
    "fox",
    "fractal",
    "frog",
    "fungus",
    "gargoyle",
    "germ",
    "giant",
    "gnoll",
    "gnome",
    "goat",
    "goblin",
    "god",
    "golem",
    "gorgon",
    "graveborn",
    "gremlin",
    "griffin",
    "guest",
    "hag",
    "halfling",
    "hamster",
    "harpy",
    "hellion",
    "hippo",
    "hippogriff",
    "homarid",
    "homunculus",
    "horror",
    "horse",
    "human",
    "hydra",
    "hyena",
    "illusion",
    "imp",
    "incarnation",
    "inkling",
    "insect",
    "jackal",
    "jellyfish",
    "juggernaut",
    "kavu",
    "kirin",
    "kithkin",
    "knight",
    "kobold",
    "kor",
    "kraken",
    "lamia",
    "lammasu",
    "leech",
    "leviathan",
    "lhurgoyf",
    "licid",
    "lizard",
    "manticore",
    "masticore",
    "mercenary",
    "merfolk",
    "metathran",
    "minion",
    "minotaur",
    "mite",
    "mole",
    "monger",
    "mongoose",
    "monk",
    "monkey",
    "moonfolk",
    "mouse",
    "mutant",
    "myr",
    "mystic",
    "naga",
    "nautilus",
    "nephilim",
    "nightmare",
    "nightstalker",
    "ninja",
    "noble",
    "noggle",
    "nomad",
    "nymph",
    "octopus",
    "ogre",
    "ooze",
    "orb",
    "orc",
    "orgg",
    "otter",
    "ouphe",
    "ox",
    "oyster",
    "pangolin",
    "peasant",
    "pegasus",
    "pentavite",
    "performer",
    "pest",
    "phelddagrif",
    "phoenix",
    "phyrexian",
    "pilot",
    "pincher",
    "pirate",
    "plant",
    "praetor",
    "prism",
    "processor",
    "rabbit",
    "raccoon",
    "ranger",
    "rat",
    "rebel",
    "reflection",
    "rhino",
    "rigger",
    "rogue",
    "sable",
    "salamander",
    "samurai",
    "sand",
    "saproling",
    "satyr",
    "scarecrow",
    "scion",
    "scorpion",
    "scout",
    "sculpture",
    "serf",
    "serpent",
    "servo",
    "shade",
    "shaman",
    "shapeshifter",
    "shark",
    "sheep",
    "siren",
    "skeleton",
    "slith",
    "sliver",
    "slug",
    "snake",
    "soldier",
    "soltari",
    "spawn",
    "specter",
    "spellshaper",
    "sphinx",
    "spider",
    "spike",
    "spirit",
    "splinter",
    "sponge",
    "squid",
    "squirrel",
    "starfish",
    "surrakar",
    "survivor",
    "tentacle",
    "tetravite",
    "thalakos",
    "thopter",
    "thrull",
    "tiefling",
    "treefolk",
    "trilobite",
    "troll",
    "turtle",
    "tyranid",
    "unicorn",
    "vampire",
    "vedalken",
    "viashino",
    "volver",
    "wall",
    "warlock",
    "warrior",
    "weird",
    "werewolf",
    "whale",
    "wizard",
    "wolf",
    "wolverine",
    "wombat",
    "worm",
    "wraith",
    "wurm",
    "yeti",
    "zombie",
    "zubera",
}

# Regex constants

SYMBOL_RE = re.compile(r"\{([^}]+)\}")

# "This land enters tapped" - the plain always-tapped statement
ENTERS_TAPPED_RE = re.compile(
    r"this land enters tapped",
    re.IGNORECASE,
)

# Shock lands: "As this land enters, you may pay 2 life. If you don't, it enters tapped."
# The key signal is the conditional "if you don't, it enters tapped" after paying life.
SHOCK_RE = re.compile(
    r"if you don't,\s+it enters tapped",
    re.IGNORECASE,
)

# Snarl / check-by-reveal lands: "you may reveal a <Type> … If you don't, this land enters tapped"
SNARL_RE = re.compile(
    r"you may reveal .+? card from your hand\. If you don't, this land enters tapped",
    re.IGNORECASE,
)

# Fast lands: "unless you control two or fewer other lands" (untapped turns 1-3)
FAST_RE = re.compile(r"unless you control two or fewer other lands", re.IGNORECASE)

# Slowlands: "unless you control two or more other lands" (untapped turns 3+)
SLOW_RE = re.compile(r"unless you control two or more other lands", re.IGNORECASE)

# Check lands: "As this land enters, you may reveal a <Type> or <Type> card from your hand"
CHECK_RE = re.compile(
    r"As this land enters, you may reveal a \w+ or \w+ card from your hand",
    re.IGNORECASE,
)

# Verge / conditional-activation lands: second tap ability gated on controlling a basic
# e.g. "{T}: Add {R}. Activate only if you control a Swamp or a Mountain."
# These don't enter tapped at all - they just conditionally produce colour.
VERGE_RE = re.compile(r"Activate only if you control", re.IGNORECASE)

# Filter lands: "{X/Y}, {X/Y}: Add" - tap + spend coloured to filter
FILTER_RE = re.compile(r"\{[WUBRGC]/[WUBRGC]\}.*?:\s*Add", re.IGNORECASE)

# Cycling
CYCLING_RE = re.compile(r"\bCycling\b", re.IGNORECASE)

# Mana rock / creature tap-for-mana: has "{T}: Add" in oracle text
ROCK_TAP_RE = re.compile(r"\{T\}\s*:\s*Add\b", re.IGNORECASE)

# Decklist line regex with named groups (qty, name, set, number)
LINE_RE = re.compile(
    r"^(?P<qty>\d+)\s+(?P<name>.+?)\s+\((?P<set>[^)]+)\)\s+(?P<number>\S+)$",
    re.IGNORECASE,
)

# Regex matching list/or patterns in oracle text such as:
#   "Angel, Demon, or Dragon"
#   "Elf or Faerie"
#   "Pirate, Vampire, Dinosaur, or Merfolk"
# Captures a comma-separated list with a trailing "or <type>".
_LIST_OR_RE = re.compile(
    r"(?:(?:an?\s+)?(?:attacking\s+)?"
    r"(\b[A-Z][a-z]+\b)"
    r"(?:\s*,\s*(?:an?\s+)?(?:attacking\s+)?(\b[A-Z][a-z]+\b))*"
    r"\s*(?:,\s*)?(?:and|or)\s+(?:an?\s+)?(?:attacking\s+)?"
    r"(\b[A-Z][a-z]+\b))",
)

# Cache compiled "context" regexes used by extract_synergy_types; each pattern
# is keyed by the exact word and reused across every commander lookup.
_CONTEXT_RE_CACHE: dict[str, re.Pattern[str]] = {}


def _context_re(word: str) -> re.Pattern[str]:
    cached = _CONTEXT_RE_CACHE.get(word)
    if cached is None:
        cached = re.compile(
            r"(?:whenever|each|other|all|target|every|a|an)\s+"
            r"(?:\w+\s+)*" + re.escape(word),
            re.IGNORECASE,
        )
        _CONTEXT_RE_CACHE[word] = cached
    return cached


# Decklist & format functions


# Arena section headers recognised by the parser.
_ARENA_SECTIONS: set[str] = {
    "commander",
    "companion",
    "deck",
    "sideboard",
}


class DecklistParseError(ValueError):
    """Raised by parse_decklist(strict=True) when a line fails to parse."""


def parse_decklist(
    path: str | Path,
    *,
    strict: bool = False,
) -> list[tuple[int, CardIdentifier]]:
    """Parse a decklist .txt file → list of (qty, CardIdentifier).

    Recognises optional Arena section headers (``Commander``, ``Deck``,
    ``Sideboard``, ``Companion``).  Cards listed under a ``Commander``
    header are guaranteed to appear first in the returned list so that
    ``entries[0]`` is always the commander - matching the convention used
    by the rest of the codebase.

    Files without headers (paper / commander format) are parsed as before:
    line 1 = commander.

    By default a malformed line emits a warning to stderr and is skipped.
    Pass ``strict=True`` (wired up as ``--strict`` on the CLI) to raise
    :class:`DecklistParseError` instead, so automation catches the failure.
    """
    commander_entries: list[tuple[int, CardIdentifier]] = []
    deck_entries: list[tuple[int, CardIdentifier]] = []
    section: str | None = None  # current Arena section, if any

    with open(path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line:
                continue
            # Detect Arena section headers
            if line.lower() in _ARENA_SECTIONS:
                section = line.lower()
                continue
            m = LINE_RE.match(line)
            if not m:
                message = f"line {lineno} does not match expected format: {line!r}"
                if strict:
                    raise DecklistParseError(f"{path}: {message}")
                print(f"WARNING: {message}, skipping", file=sys.stderr)
                continue
            entry = (
                int(m.group("qty")),
                CardIdentifier(
                    set_code=m.group("set"),
                    collector_number=m.group("number"),
                    name=m.group("name"),
                ),
            )
            if section == "commander":
                commander_entries.append(entry)
            else:
                deck_entries.append(entry)

    return commander_entries + deck_entries


def detect_format(decklist_path: str | Path) -> str:
    """Auto-detect format from decklist path. Fallback: 'commander'."""
    parts = Path(decklist_path).parts
    for part in parts:
        low = part.lower()
        if low in FORMAT_TARGETS:
            return low
    return "commander"


# Card data helper functions


# Per-card memo key. Derived helpers (oracle_text, type_line, produced_mana,
# land_speed, etc.) are invoked many times per card during pipeline runs
# (analyze + review back-to-back). Caching the derived values on the card dict
# under a single well-known key avoids re-running regex-heavy logic.
_MEMO_KEY = "_ms_memo"


def _memo(card: dict, key: str, compute):
    """Return a cached value for ``key`` on ``card``, computing it on first use.

    The cache is a plain dict stored on the card under ``_MEMO_KEY``. Because
    Scryfall card dicts are reused across analyze/review within a single run,
    this eliminates redundant oracle-text/regex work without any global state.
    """
    memo = card.get(_MEMO_KEY)
    if memo is None:
        memo = {}
        card[_MEMO_KEY] = memo
    if key in memo:
        return memo[key]
    value = compute()
    memo[key] = value
    return value


def _compute_oracle_text(card: dict) -> str:
    top = card.get("oracle_text")
    if top is not None:
        return top
    faces = card.get("card_faces", [])
    return " // ".join(f.get("oracle_text", "") for f in faces)


def oracle_text(card: dict) -> str:
    """Return the full oracle text of a card, joining faces with ' // '."""
    return _memo(card, "oracle_text", lambda: _compute_oracle_text(card))


def _compute_type_line(card: dict) -> str:
    top = card.get("type_line", "")
    if top:
        return top
    faces = card.get("card_faces", [])
    return " // ".join(f.get("type_line", "") for f in faces)


def type_line(card: dict) -> str:
    """Return the full type line of a card, joining faces with ' // '."""
    return _memo(card, "type_line", lambda: _compute_type_line(card))


def _compute_card_subtypes(card: dict) -> set[str]:
    tl = type_line(card)
    if "—" in tl:
        return {s.strip().lower() for s in tl.split("—", 1)[1].split()}
    return set()


def card_subtypes(card: dict) -> set[str]:
    """Return the set of subtypes from the type line (everything after '-'), lowercased."""
    return _memo(card, "card_subtypes", lambda: _compute_card_subtypes(card))


def mana_cost(card: dict) -> str:
    """Extract the mana cost string from a Scryfall card object.

    Single-faced cards carry ``mana_cost`` at the top level.
    Double-faced cards carry it on each face; costs are joined with
    ``' // '`` to match decklist conventions.  Lands and other
    no-cost permanents return ``''``.
    """
    top = card.get("mana_cost")
    if top is not None:
        return top
    faces = card.get("card_faces", [])
    if faces:
        costs = [f.get("mana_cost", "") for f in faces if f.get("mana_cost")]
        return " // ".join(costs)
    return ""


def is_land(card: dict) -> bool:
    """Return True if the card is a Land."""
    return "Land" in type_line(card)


def is_artifact(card: dict) -> bool:
    """Return True if the card is an Artifact."""
    return "Artifact" in type_line(card)


def is_creature(card: dict) -> bool:
    """Return True if the card is a Creature."""
    return "Creature" in type_line(card)


def card_type_category(card: dict) -> str:
    """Return the primary card type as a lowercase category string.

    Categories (checked in priority order): ``'land'``, ``'creature'``,
    ``'artifact'``, ``'enchantment'``, ``'instant'``, ``'sorcery'``,
    ``'planeswalker'``, ``'battle'``, or ``'other'``.

    Artifact creatures are classified as ``'creature'`` because that is
    their most strategically relevant type.
    """
    tl = type_line(card).lower()
    if "land" in tl:
        return "land"
    if "creature" in tl:
        return "creature"
    if "instant" in tl:
        return "instant"
    if "sorcery" in tl:
        return "sorcery"
    if "planeswalker" in tl:
        return "planeswalker"
    if "battle" in tl:
        return "battle"
    if "artifact" in tl:
        return "artifact"
    if "enchantment" in tl:
        return "enchantment"
    return "other"


def _compute_produced_mana(card: dict) -> set[str]:
    pm = card.get("produced_mana")
    if pm:
        return set(pm)
    # Fallback: scan oracle text for tap-to-add lines
    text = oracle_text(card)
    syms: set[str] = set()
    for line in text.splitlines():
        if ROCK_TAP_RE.search(line):
            for sym in SYMBOL_RE.findall(line):
                if sym in {"W", "U", "B", "R", "G", "C", "S"}:
                    syms.add(sym)
    return syms


def produced_mana(card: dict) -> set[str]:
    """Return the set of mana symbols this card can produce.

    Derived from Scryfall's produced_mana field. Falls back to parsing
    '{T}: Add {X}' oracle lines if the field is absent.
    """
    return _memo(card, "produced_mana", lambda: _compute_produced_mana(card))


def _compute_land_speed(card: dict) -> str:
    """Classify a land's entry speed from its oracle text.

    Categories:
      'untapped'    - reliably enters untapped with no downside
                      (basics, utility lands, verge/conditional-activation lands
                       that don't enter tapped at all)
      'shock'       - enters tapped unless you pay 2 life
                      ("As this land enters, you may pay 2 life. If you don't,
                      it enters tapped.")
      'conditional' - enters tapped unless a board condition is met
                      (fast lands, slow lands, check lands, snarl lands, filter
                      lands)
      'tapped'      - always enters tapped, no opt-out

    Detection order matters: shock and conditional patterns are checked before
    the plain 'enters tapped' fallback so they are never mis-classified.
    """
    text = oracle_text(card)

    # Shock lands: conditional on paying 2 life - check before plain tapped test
    if SHOCK_RE.search(text):
        return "shock"

    # Verge / conditional-activation lands never enter tapped at all -
    # their second ability is simply gated on a board condition.
    if VERGE_RE.search(text) and not ENTERS_TAPPED_RE.search(text):
        return "conditional"

    # Everything below this point must contain some form of "enters tapped"
    if not ENTERS_TAPPED_RE.search(text):
        return "untapped"

    # Snarl lands (reveal from hand opt-out)
    if SNARL_RE.search(text):
        return "conditional"

    # Fast lands (untapped only with ≤2 other lands)
    if FAST_RE.search(text):
        return "conditional"

    # Slow lands (untapped only with ≥2 other lands)
    if SLOW_RE.search(text):
        return "conditional"

    # Check lands ("unless you control a <Type> or <Type>")
    if CHECK_RE.search(text):
        return "conditional"

    # Filter lands (spend coloured mana to filter)
    if FILTER_RE.search(text):
        return "conditional"

    return "tapped"


def land_speed(card: dict) -> str:
    """Memoized wrapper around :func:`_compute_land_speed`."""
    return _memo(card, "land_speed", lambda: _compute_land_speed(card))


def _taps_for_mana(card: dict) -> bool:
    return _memo(card, "taps_for_mana", lambda: bool(ROCK_TAP_RE.search(oracle_text(card))))


def is_mana_rock(card: dict) -> bool:
    """Check if this card is a non-land artifact that can tap to add mana.

    Excludes lands (they are handled separately).
    """
    return not is_land(card) and is_artifact(card) and _taps_for_mana(card)


def is_mana_creature(card: dict) -> bool:
    """Check if this card is a creature (non-land) that can tap to add mana."""
    return not is_land(card) and is_creature(card) and _taps_for_mana(card)


def rock_land_equiv(card: dict) -> float:
    """Estimate the land-equivalent value of a mana rock or mana creature.

    Uses Frank Karsten's Commander mana-base methodology:

      0-1 CMC rock producing 2+ mana  → 1.0
      2   CMC rock producing 1 mana   → 0.5
      3   CMC rock                    → 0.3
      4+  CMC rock / devotion-based   → 0.0
      Mana creature (fragile)         → 0.3

    All values are derived from the card's actual CMC and oracle text - nothing
    is hardcoded per card name.
    """
    cmc = card.get("cmc", 0.0)
    text = oracle_text(card)

    if is_mana_creature(card):
        return 0.3

    # Count how much mana the rock produces per tap from oracle lines
    mana_out = 0
    for line in text.splitlines():
        if ROCK_TAP_RE.search(line):
            syms = SYMBOL_RE.findall(line)
            mana_out = sum(
                (int(s) if s.isdigit() else 1)
                for s in syms
                if s in {"W", "U", "B", "R", "G", "C"} or s.isdigit()
            )
            break

    if cmc <= 1 and mana_out >= 2:
        return 1.0
    if cmc <= 2:
        return 0.5
    if cmc <= 3:
        return 0.3
    return 0.0


def has_synergy_type(card: dict, synergy_types: set[str]) -> bool:
    """Check if this card has at least one subtype that matches the commander's.

    Changeling creatures have every creature type and always qualify.
    """
    if not synergy_types:
        return False
    subtypes = {s.lower() for s in card_subtypes(card)}
    if "changeling" in subtypes:
        return True
    return bool(subtypes & synergy_types)


def pip_colours(mana_cost: str, colours: set[str]) -> list[str]:
    """Return a flat list of colour pip symbols found in a mana cost string."""
    pips = []
    for sym in SYMBOL_RE.findall(mana_cost):
        parts = sym.split("/")
        for p in parts:
            if p in colours:
                pips.append(p)
    return pips


def card_cmc_from_cost(mana_cost: str) -> int:
    """Calculate CMC from a mana cost string by summing numeric values.

    Counts each non-numeric, non-X symbol as 1.
    Used for mana-curve display when the Scryfall cmc field might be unavailable.
    """
    total = 0
    for sym in SYMBOL_RE.findall(mana_cost):
        if sym.isdigit():
            total += int(sym)
        elif sym.upper() != "X":
            total += 1
    return total


# Legality & identity functions


def is_legal(card_json: dict, fmt: str) -> bool:
    """Check if a card is legal in the given format."""
    field = FORMAT_LEGALITY_FIELD.get(fmt, fmt)
    return card_json.get("legalities", {}).get(field) == "legal"


def colour_identity(card_json: dict) -> set[str]:
    """Return the colour identity of a card as a set of colours."""
    return set(card_json.get("color_identity", []))


def is_within_identity(card_json: dict, identity: set[str]) -> bool:
    """Check if a card's colour identity is within the given identity set."""
    return colour_identity(card_json).issubset(identity)


# Synergy extraction


def extract_synergy_types(commander: dict) -> set[str]:
    """Derive a set of creature types that the commander cares about.

    Strategy:
    1. Scan the commander's oracle text for list/or patterns of creature types
       (e.g. "Angel, Demon, or Dragon").
    2. Also include the commander's own subtypes that are creature types.
    3. If nothing is found from oracle text, fall back to subtypes only.
    """
    text = oracle_text(commander)
    subtypes = card_subtypes(commander)

    # --- Phase 1: find creature-type words in oracle text list/or patterns ---
    oracle_types: set[str] = set()

    # Use a simpler, more robust approach: find all capitalised words in the
    # oracle text that are known creature types and appear near "or" / ","
    # list constructions.
    # First, try to find explicit list patterns.
    for m in _LIST_OR_RE.finditer(text):
        for g in m.groups():
            if g and g.lower() in CREATURE_TYPES:
                oracle_types.add(g.lower())

    # If we found no list-pattern types, also try individual mentions in
    # characteristic oracle-text patterns like "whenever a <Type> enters"
    if not oracle_types:
        # Look for "whenever ... <Type>" or "each <Type>" or "other <Types>"
        for word in re.findall(r"\b([A-Z][a-z]+)\b", text):
            wl = word.lower()
            # _context_re is module-level cached per word to avoid
            # recompiling the same pattern on every iteration.
            # Only include if the word names a creature type AND appears in
            # a meaningful context (near "whenever", "each", "other", etc.).
            if wl in CREATURE_TYPES and _context_re(word).search(text):
                oracle_types.add(wl)

    # --- Phase 2: merge with commander's own subtypes ---
    subtype_creatures = {s for s in subtypes if s in CREATURE_TYPES}

    synergy = oracle_types | subtype_creatures

    return synergy


# Display helpers


def sorted_colours(colours: set[str]) -> list[str]:
    """Return colours in WUBRG order."""
    return [c for c in WUBRG_ORDER if c in colours]


def colour_balance(
    source_count: Counter,
    pip_counts: Counter,
    total_lands: int,
    total_pips: int,
    colours: set[str],
) -> dict[str, tuple[float, float, float]]:
    """Return dict of colour → (src_pct, pip_pct, delta)."""
    result: dict[str, tuple[float, float, float]] = {}
    for col in sorted_colours(colours):
        src_pct = source_count[col] / total_lands * 100 if total_lands else 0.0
        pip_pct = pip_counts[col] / total_pips * 100 if total_pips else 0.0
        result[col] = (src_pct, pip_pct, src_pct - pip_pct)
    return result
