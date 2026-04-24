"""EDHREC deck review and owned-card upgrade candidates command module.

Produces two sections: an EDHREC cross-reference that compares decklist
contents against popular picks, and an owned upgrade candidates scan that
searches the user's collection for theme-relevant cards not yet in the deck.
Card helpers come from :mod:`manascope.deck`, collection loading from
:mod:`manascope.collection`, and the CLI layer (Typer) handles argument parsing.
"""

import json
import re
import sqlite3
import sys
from pathlib import Path

from manascope import DB_PATH, deck
from manascope import edhrec as ec
from manascope import scryfall as sc
from manascope.collection import load_collection

# Constants

# Mapping from EDHREC theme tag slugs to (type_line_pattern, oracle_text_pattern).
# At least one pattern per entry must be non-None.  The collection-scan section
# calls ec.tags() for the commander, walks this dict in EDHREC popularity order,
# and uses the matching patterns to find owned cards for each theme.
SLUG_PATTERNS: dict[str, tuple[str | None, str | None]] = {
    # -- tribal ---------------------------------------------------------------
    "faeries": (r"\bfaerie\b", r"\bfaerie\b"),
    "elves": (r"\belf\b|\belves\b", r"\belf\b|\belves\b"),
    "rogues": (r"\brogue\b", r"\brogue\b"),
    "druids": (r"\bdruid\b", r"\bdruid\b"),
    "warriors": (r"\bwarrior\b", r"\bwarrior\b"),
    "wizards": (r"\bwizard\b", r"\bwizard\b"),
    "shapeshifters": (r"\bshapeshifter\b", r"\bshapeshifter\b"),
    "legends": (r"\blegendary\b", None),
    "planeswalkers": (r"\bplaneswalker\b", None),
    "artifacts": (r"\bartifact\b", None),
    # -- mechanics ------------------------------------------------------------
    "flash": (None, r"\bflash\b"),
    "tokens": (None, r"create a .{1,40} token"),
    "flying": (None, r"\bflying\b"),
    "card-draw": (None, r"draw (a|\d+) card"),
    "ramp": (None, r"add \{[BGRUW0-9]"),
    "graveyard": (None, r"from (your )?graveyard"),
    "reanimator": (None, r"return .{1,40}from .{0,20}graveyard to .{0,20}battlefield"),
    "blink": (None, r"exile .{1,60}return .{0,20}(to|onto) the battlefield"),
    "plus-1-plus-1-counters": (None, r"\+1/\+1 counter"),
    "minus-1-minus-1-counters": (None, r"-1/-1 counter"),
    "etb": (None, r"when .{0,60}enters"),
    "mill": (None, r"\bmill\b"),
    "self-mill": (None, r"\bmill\b"),
    "exile": (None, r"\bexile\b"),
    "bounce": (
        None,
        r"return .{1,40}to .{0,20}(its owner|their owner|your).{0,10}hand",
    ),
    "counterspells": (None, r"counter target (spell|ability)"),
    "control": (None, r"counter target|destroy target|exile target"),
    "theft": (None, r"cast .{0,60}without paying|cast .{0,60}from .{0,40}exile"),
    "populate": (None, r"\bpopulate\b"),
    "clones": (None, r"\bcopy (of|target)|become a copy"),
    "spellslinger": (None, r"whenever you cast .{0,20}(instant|sorcery)"),
    "aristocrats": (None, r"whenever (a |another )?creature dies"),
    "scry": (None, r"\bscry\b"),
    "surveil": (None, r"\bsurveil\b"),
    "enchantress": (None, r"whenever (you cast|an? enchantment).{0,40}enter"),
    "tap-untap": (None, r"\buntap\b"),
    "lifegain": (None, r"gain \d+ life|you gain life"),
    "lifedrain": (None, r"(opponent|player).{0,30}loses? .{0,10}life"),
    "discard": (None, r"\bdiscard\b"),
    "extra-turns": (None, r"take an extra turn"),
    "storm": (None, r"\bstorm\b"),
    "dredge": (None, r"\bdredge\b"),
    "flashback": (None, r"\bflashback\b"),
    "infect": (None, r"\binfect\b"),
    "energy": (None, r"\{E\}"),
    "anthems": (None, r"get \+\d/\+\d"),
    "commander-matters": (None, r"\byour commander\b"),
    "forced-combat": (None, r"must attack|attacks .{0,20}if able"),
    "stax": (None, r"can't .{0,40}unless|opponents can't"),
    "burn": (None, r"deals? \d+ damage to .{0,20}(any target|player|opponent)"),
    "big-mana": (None, r"add .{1,10}mana of any|double .{0,20}mana"),
    "amass": (None, r"\bamass\b"),
    "crime": (None, r"\bcrime\b"),
    "proliferate": (None, r"\bproliferate\b"),
}

# Fallback used when EDHREC data is unavailable (covers common mechanics
# without assuming any particular commander strategy).
_FALLBACK_THEMES: list[tuple[str, str | None, str | None]] = [
    ("Flash", None, r"\bflash\b"),
    ("Tokens", None, r"create a .{1,40} token"),
    ("Draw", None, r"draw (a|\d+) card"),
    ("Ramp", None, r"add \{[BGRUW0-9]"),
    ("Tutor / Search", None, r"search your (library|deck)"),
    ("Removal", None, r"destroy target|exile target|counter target"),
    ("Graveyard", None, r"from (your )?graveyard"),
    ("Flying", None, r"\bflying\b"),
    ("+1/+1 Counters", None, r"\+1/\+1 counter"),
]

W = 76  # output width


# Output helpers


def _sep(char: str = "-", width: int = W) -> str:
    return char * width


def _section_header(title: str, count: int, note: str = "") -> None:
    print()
    print(_sep("="))
    suffix = f"  - {note}" if note else ""
    print(f"  {title}  ({count}){suffix}")
    print(_sep("="))


def _col_header() -> None:
    print(f"  {'Card':<35}  {'Type':<14}  {'CMC':>3}  {'Syn':>4}  {'Inc%':>5}  {'Status'}")
    print("  " + _sep("-", W - 2))


def _card_row(card: ec.SynergyCard, type_abbr: str = "", cmc: str = "", status: str = "") -> None:
    name = card.name[:35]
    print(
        f"  {name:<35}  {type_abbr:<14}  {cmc:>3}  {card.synergy_pct:>3}%  {card.inclusion_pct:>4.0f}%  {status}"
    )


def _type_abbr(cj: dict | None) -> str:
    """Short type abbreviation for display (e.g. 'Creature', 'Instant')."""
    if cj is None:
        return ""
    tl = deck.type_line(cj)
    # Return first major type
    for t in (
        "Creature",
        "Instant",
        "Sorcery",
        "Artifact",
        "Enchantment",
        "Planeswalker",
        "Battle",
        "Land",
    ):
        if t.lower() in tl.lower():
            return t
    return ""


def _cmc_str(cj: dict | None) -> str:
    """CMC as a display string."""
    if cj is None:
        return ""
    cmc = cj.get("cmc", 0)
    return str(int(cmc))


# Cache helpers


def _lookup_json(conn: sqlite3.Connection, name: str) -> dict | None:
    """Return the parsed full_json for a card by name, or None if not cached."""
    row = conn.execute(
        "SELECT full_json FROM cards WHERE LOWER(name) = LOWER(?)", (name,)
    ).fetchone()
    if not row:
        # Double-faced cards stored as "Front // Back"
        row = conn.execute(
            r"SELECT full_json FROM cards WHERE LOWER(name) LIKE LOWER(?) ESCAPE '\'",
            (sc._escape_like(name) + " // %",),
        ).fetchone()
    return json.loads(row[0]) if row else None


# Theme matching


# Module-level compile cache for theme regexes.
# SLUG_PATTERNS and _FALLBACK_THEMES are filled with raw strings for
# readability; we compile each unique pattern at most once and reuse it.
_RE_CACHE: dict[str, re.Pattern[str]] = {}


def _compiled(pattern: str | None) -> re.Pattern[str] | None:
    if pattern is None:
        return None
    cached = _RE_CACHE.get(pattern)
    if cached is None:
        cached = re.compile(pattern, re.IGNORECASE)
        _RE_CACHE[pattern] = cached
    return cached


def _matches_theme(cj: dict, type_pat: str | None, text_pat: str | None) -> bool:
    tl = deck.type_line(cj)
    tx = deck.oracle_text(cj)
    type_re = _compiled(type_pat)
    if type_re is not None and type_re.search(tl):
        return True
    text_re = _compiled(text_pat)
    return bool(text_re is not None and text_re.search(tl + " " + tx))


# EDHREC cross-reference


def run_edhrec_section(
    *,
    commander_name: str,
    deck_names: set[str],
    conn: sqlite3.Connection,
    owned: dict[str, dict],
    fmt: str,
    top_n: int,
    edhrec_data: dict | None = None,
    compact: bool = False,
    agent: bool = False,
    json_flag: bool = False,
    return_data: bool = False,
) -> dict | None:
    """Run the EDHREC cross-reference section."""
    verbose = not (agent or json_flag)
    if verbose:
        print()
        print(_sep("="))
        print(f"  EDHREC CROSS-REFERENCE  -  {commander_name}")
        print(_sep("="))

    data = edhrec_data if edhrec_data is not None else ec.fetch_commander(conn, commander_name)
    if data is None:
        print(f"  ERROR: no EDHREC data found for {commander_name!r}.")
        print("  Ensure the commander name matches the EDHREC slug exactly,")
        print('  or run:  uv run manascope prime "<Commander Name>"  to prime the cache.')
        return

    num_decks = ec.num_decks(data)
    all_recs = ec.all_recommended_cards(data)
    evaluated = all_recs[:top_n]

    if verbose:
        print(f"  {num_decks:,} Commander decks sampled  ·  evaluating top {top_n} by synergy")
        print(f"  Format legality check: {fmt}")
        if owned:
            print(f"  Collection loaded: {len(owned):,} unique cards")

    # Classify
    in_deck: list[ec.SynergyCard] = []
    gap_owned: list[ec.SynergyCard] = []
    gap_unowned: list[ec.SynergyCard] = []
    not_legal: list[ec.SynergyCard] = []
    not_cached: list[ec.SynergyCard] = []

    card_data: dict[str, dict | None] = {}

    for card in evaluated:
        cj = _lookup_json(conn, card.name)
        if cj is None:
            not_cached.append(card)
            continue
        card_data[card.name] = cj
        if not deck.is_legal(cj, fmt):
            not_legal.append(card)
            continue
        if card.name.lower() in deck_names:
            in_deck.append(card)
        elif card.name.lower() in owned:
            gap_owned.append(card)
        else:
            gap_unowned.append(card)

    if json_flag or return_data:
        import json

        out_data = {
            "stats": {
                "sample": num_decks,
                "in_deck": len(in_deck),
                "gaps_owned": len(gap_owned),
                "gaps_not_owned": len(gap_unowned),
                "skipped": len(not_cached),
            },
            "in_deck": [
                {
                    "name": c.name,
                    "synergy": c.synergy_pct,
                    "type": _type_abbr(card_data.get(c.name)),
                    "cmc": (card_data.get(c.name) or {}).get("cmc", 0),
                }
                for c in in_deck
            ],
            "gaps_owned": [
                {
                    "name": c.name,
                    "synergy": c.synergy_pct,
                    "type": _type_abbr(card_data.get(c.name)),
                    "cmc": (card_data.get(c.name) or {}).get("cmc", 0),
                }
                for c in gap_owned
            ],
            "gaps_not_owned": [
                {
                    "name": c.name,
                    "synergy": c.synergy_pct,
                    "type": _type_abbr(card_data.get(c.name)),
                    "cmc": (card_data.get(c.name) or {}).get("cmc", 0),
                }
                for c in gap_unowned[:20]
            ],
        }
        if return_data:
            return out_data
        print(json.dumps(out_data))
        return None

    if agent:
        print(
            f"[EDHREC Stats] Sample:{num_decks}, InDeck:{len(in_deck)}, "
            f"GapsOwned:{len(gap_owned)}, GapsNotOwned:{len(gap_unowned)}"
        )
        go_str = [f"{c.name}({c.synergy_pct}%)" for c in gap_owned]
        print(f"[Gaps Owned] {', '.join(go_str)}")
        gu_str = [f"{c.name}({c.synergy_pct}%)" for c in gap_unowned[:20]]
        print(f"[Gaps Not Owned (Top 20)] {', '.join(gu_str)}")
        if not_cached:
            print(f"[Skipped] {len(not_cached)} not cached.")
        return

    # --- 1: In deck ---
    if compact:
        print(f"\n--- 1. IN DECK ({len(in_deck)}) ---")
    else:
        _section_header("1. ALREADY IN DECK", len(in_deck), "good coverage")
        _col_header()
    for c in in_deck:
        _card_row(
            c, _type_abbr(card_data.get(c.name)), _cmc_str(card_data.get(c.name)), "* in deck"
        )

    # --- Lowest synergy (potential cut candidates) ---
    if len(in_deck) >= 5 and not compact:
        bottom = in_deck[-5:]  # already sorted descending, so last 5 are lowest
        print()
        print("  ┌─ Lowest synergy in your deck (potential cut candidates):")
        for c in reversed(bottom):  # show ascending (worst first)
            ta = _type_abbr(card_data.get(c.name))
            cm = _cmc_str(card_data.get(c.name))
            print(f"  │  {c.name:<35}  {ta:<14}  {cm:>3}  {c.synergy_pct:>3}%")
        print("  └─")

    # --- 2: Owned gaps - primary target ---
    if compact:
        print(f"\n--- 2. LEGAL + OWNED, MISSING ({len(gap_owned)}) ---")
    else:
        _section_header(
            "2. LEGAL + OWNED - MISSING FROM DECK",
            len(gap_owned),
            "★ primary upgrade targets ★",
        )
        _col_header()
    for c in gap_owned:
        _card_row(c, _type_abbr(card_data.get(c.name)), _cmc_str(card_data.get(c.name)), "owned")

    # --- 3: Legal, not owned ---
    if compact:
        print(f"\n--- 3. LEGAL, NOT OWNED ({len(gap_unowned)}) ---")
    else:
        _section_header("3. LEGAL - NOT OWNED", len(gap_unowned), "FYI only")
        _col_header()
    for c in gap_unowned:
        _card_row(c, _type_abbr(card_data.get(c.name)), _cmc_str(card_data.get(c.name)))

    # --- 4: Not format-legal ---
    if compact:
        print(f"\n--- 4. NOT FORMAT-LEGAL ({len(not_legal)}) ---")
    else:
        _section_header(
            "4. NOT FORMAT-LEGAL",
            len(not_legal),
            "Commander-only or rotated - substitutes needed",
        )
        _col_header()
    for c in not_legal:
        _card_row(
            c, _type_abbr(card_data.get(c.name)), _cmc_str(card_data.get(c.name)), "not legal"
        )

    if not_cached:
        print()
        print(
            f"  [{len(not_cached)} card(s) skipped - not in local cache; "
            "run 'uv run manascope lookup' to fetch]"
        )

    # Summary
    print()
    print(_sep("="))
    print("  EDHREC SUMMARY")
    print(_sep("-"))
    print(f"  In deck              : {len(in_deck)}")
    print(f"  Gaps (owned)         : {len(gap_owned)}   ← review these")
    print(f"  Gaps (not owned)     : {len(gap_unowned)}")
    print(f"  Not format-legal     : {len(not_legal)}")
    if not_cached:
        print(f"  Not cached           : {len(not_cached)}")
    print(_sep("="))


# Owned upgrade candidates


def run_collection_section(
    *,
    conn: sqlite3.Connection,
    owned: dict[str, dict],
    deck_names: set[str],
    colour_identity: set[str],
    fmt: str,
    edhrec_data: dict | None = None,
    max_themes: int = 12,
    min_tag_decks: int = 20,
) -> None:
    """Scan owned cards for upgrade candidates, grouped by EDHREC themes."""
    # Gather candidates: owned, legal, within colour identity, not in deck
    candidates: list[dict] = []
    # Stream rows and pre-filter on the cheap name check before paying
    # for json.loads: only parse full_json for owned, not-in-deck cards.
    cur = conn.execute("SELECT name, full_json FROM cards")

    for name, full_json in cur:
        low = name.lower()
        if low in deck_names:
            continue
        if low not in owned:
            continue
        cj = json.loads(full_json)
        if not deck.is_legal(cj, fmt):
            continue
        if not deck.is_within_identity(cj, colour_identity):
            continue

        candidates.append(
            {
                "name": name,
                "type_line": deck.type_line(cj),
                "cmc": cj.get("cmc", 0),
                "ci": "".join(sorted(deck.colour_identity(cj))) or "C",
                "text": deck.oracle_text(cj),
                "cj": cj,
            }
        )

    candidates.sort(key=lambda x: (x["cmc"], x["name"]))

    ci_label = "".join(c for c in deck.WUBRG_ORDER if c in colour_identity) or "C"

    print()
    print(_sep("="))
    print("  OWNED UPGRADE CANDIDATES")
    print(f"  Owned · {fmt}-legal · colour identity {{{ci_label}}} · not in deck")
    print(f"  {len(candidates)} cards found")
    print(_sep("="))

    # Build theme list from EDHREC tags (commander-specific) when available;
    # fall back to the built-in generic mechanic list otherwise.
    if edhrec_data is not None:
        themes: list[tuple[str, str | None, str | None]] = []
        for tag in ec.tags(edhrec_data):
            if tag.deck_count < min_tag_decks:
                continue
            patterns = SLUG_PATTERNS.get(tag.slug)
            if patterns is None:
                continue
            themes.append((tag.name, patterns[0], patterns[1]))
            if len(themes) >= max_themes:
                break
        if not themes:
            themes = list(_FALLBACK_THEMES)
    else:
        themes = list(_FALLBACK_THEMES)

    shown: set[str] = set()

    for label, type_pat, text_pat in themes:
        hits = [c for c in candidates if _matches_theme(c["cj"], type_pat, text_pat)]
        if not hits:
            continue

        print()
        print(f"  {_sep('-', W - 2)}")
        print(f"  {label.upper()}  ({len(hits)} cards)")
        print(f"  {_sep('-', W - 2)}")
        print(f"  {'':1}  {'Card':<42}  {'CMC':>3}  {'CI'}")

        for cd in hits:
            marker = "★" if cd["name"] not in shown else " "
            shown.add(cd["name"])
            print(f"  {marker} {cd['name']:<42}  {cd['cmc']:>3.0f}  [{cd['ci']}]")
            snippet = cd["text"].replace("\n", " ")[:100]
            if snippet:
                print(f"       {snippet}")

    print()
    print(_sep("="))


# Main entry point


def run(
    decklist: str,
    collection: str | list[str] | None = None,
    top: int = 80,
    fmt: str | None = None,
    no_candidates: bool = False,
    compact: bool = False,
    agent: bool = False,
    json_flag: bool = False,
    cache: str = str(DB_PATH),
    return_data: bool = False,
    strict: bool = False,
) -> dict | None:
    """Run the EDHREC deck review and (optionally) owned-upgrade-candidates scan."""
    fmt = fmt or deck.detect_format(decklist)
    verbose = not (agent or json_flag)

    # ------------------------------------------------------------------
    # Load decklist & resolve commander via Scryfall cache
    # ------------------------------------------------------------------
    if verbose:
        print(f"Opening cache: {cache}")
    cache_conn = sc.open_cache(Path(cache))

    txt_entries = deck.parse_decklist(decklist, strict=strict)
    if not txt_entries:
        cache_conn.close()
        print("ERROR: no valid decklist entries found.", file=sys.stderr)
        sys.exit(1)

    identifiers = [ident for _, ident in txt_entries]
    try:
        card_map = sc.load_decklist_cards(cache_conn, identifiers, verbose=verbose)
    finally:
        cache_conn.close()
    if verbose:
        print()

    # Commander is first line
    cmd_ident = txt_entries[0][1]
    cmd_key = (cmd_ident.set_code.lower(), cmd_ident.collector_number.lower())
    cmd_card = card_map.get(cmd_key)
    if cmd_card is None:
        print(f"ERROR: commander {cmd_ident.name!r} not found in cache.", file=sys.stderr)
        sys.exit(1)

    commander_name: str = cmd_card.get("name", cmd_ident.name)
    colour_identity: set[str] = set(cmd_card.get("color_identity", []))

    # Build set of current deck card names (lower-cased).
    # Fall back to the decklist name when a specific printing isn't in the
    # Scryfall cache (e.g. ECL set codes, alternate prints) so that in-deck
    # cards are never misclassified as EDHREC gaps.
    # For DFCs stored as "Front // Back", also index the front face name alone
    # so that EDHREC references (which use the front face only) match correctly.
    # This mirrors the reverse lookup already done in _lookup_json.
    deck_names: set[str] = set()
    for _, ident in txt_entries:
        key = (ident.set_code.lower(), ident.collector_number.lower())
        cj = card_map.get(key)
        if cj:
            full_name = cj.get("name", ident.name)
            deck_names.add(full_name.lower())
            if " // " in full_name:
                deck_names.add(full_name.split(" // ")[0].lower())
        else:
            deck_names.add(ident.name.lower())

    # ------------------------------------------------------------------
    # Load collection (optional)
    # ------------------------------------------------------------------
    owned: dict[str, dict] = {}
    if collection:
        try:
            if isinstance(collection, list):
                from manascope.collection import load_collections

                owned = load_collections([Path(p) for p in collection])
                if verbose:
                    print(
                        f"Collection: {len(owned):,} unique cards loaded from {len(collection)} file(s)"
                    )
            else:
                owned = load_collection(Path(collection))
                if verbose:
                    print(f"Collection: {len(owned):,} unique cards loaded from {collection}")
        except OSError as e:
            print(f"WARNING: could not read collection file: {e}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Print header
    # ------------------------------------------------------------------
    ci_label = "".join(c for c in deck.WUBRG_ORDER if c in colour_identity) or "C"
    if verbose:
        print()
        print(_sep("="))
        print(f"  DECK REVIEW  -  {commander_name.upper()}")
        print(f"  Decklist : {decklist}")
        print(f"  Format   : {fmt}")
        print(f"  Colours  : {ci_label}")
        print(f"  Deck     : {sum(q for q, _ in txt_entries)} cards")
        print(_sep("="))

    # ------------------------------------------------------------------
    # Re-open the shared cache for EDHREC + collection scan. Using
    # sc.open_cache (rather than sqlite3.connect directly) guarantees the
    # cards schema and performance pragmas are in place.
    # ------------------------------------------------------------------
    conn = sc.open_cache(Path(cache))
    try:
        edhrec_data = ec.fetch_commander(conn, commander_name)

        out_data = run_edhrec_section(
            commander_name=commander_name,
            deck_names=deck_names,
            conn=conn,
            owned=owned,
            fmt=fmt,
            top_n=top,
            edhrec_data=edhrec_data,
            compact=compact,
            agent=agent,
            json_flag=json_flag,
            return_data=return_data,
        )

        if return_data:
            return out_data

        if collection and not no_candidates and verbose:
            run_collection_section(
                conn=conn,
                owned=owned,
                deck_names=deck_names,
                colour_identity=colour_identity,
                fmt=fmt,
                edhrec_data=edhrec_data,
            )
    finally:
        conn.close()
    if verbose:
        print()
        print("Done.")
