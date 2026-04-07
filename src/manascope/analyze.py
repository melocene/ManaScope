"""Mana-base and deck composition analysis command module.

Computes land counts, colour balance, mana curve, and synergy metrics for a
decklist, then outputs results via the ``DeckStats`` dataclass in JSON, agent,
or human-readable format. Card helpers live in :mod:`manascope.deck`; Scryfall
cache access is via :mod:`manascope.scryfall`.
"""

import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from manascope import DB_PATH, deck
from manascope import scryfall as sc

# ---------------------------------------------------------------------------
# Display helper (kept local - presentation-only)
# ---------------------------------------------------------------------------


def print_separator(title: str = "", width: int = 72) -> None:
    """Print a simple divider."""
    print("-" * width)
    if title:
        print(title)
        print("-" * width)
    print()


# ---------------------------------------------------------------------------
# Computed analysis results
# ---------------------------------------------------------------------------


@dataclass
class DeckStats:
    """Computed analysis results for a single deck."""

    commander_name: str
    decklist: str
    deck_format: str
    cache_path: str
    card_count: int

    # Colour info
    sorted_colours: list[str]
    colour_identity: set[str]
    synergy_types: set[str]
    commander_cmc: float

    # Partition
    lands: list[dict]
    spells: list[dict]
    total_lands: int
    total_spells: int

    # Type distribution
    type_distribution: Counter

    # Mana sources
    source_count: Counter
    speed_counts: Counter
    pip_counts: Counter
    needs_colour: Counter
    total_pips: int

    # Rocks & creatures
    rocks: list[dict]
    mana_creatures: list[dict]
    rock_total: float
    effective_land_count: float

    # Synergy
    synergy_targets: list[dict]
    non_synergy_creatures: list[dict]

    # Curve
    cmc_counter: Counter

    # Balance
    balance_data: dict

    # Targets
    eff_low: float
    eff_high: float
    land_target_label: str

    # Card map (for display)
    card_map_size: int


# ---------------------------------------------------------------------------
# Phase 1-3: Load, resolve, expand, compute
# ---------------------------------------------------------------------------


def _compute_stats(
    decklist: str,
    cache: str,
    fmt: str | None,
    verbose: bool,
) -> DeckStats:
    """Load card data, resolve the commander, and compute all deck statistics.

    This covers format detection, cache loading, commander resolution,
    colour-identity derivation, card expansion, and every Counter computation.
    """
    # Auto-detect format if not explicitly provided
    deck_format: str = fmt if fmt else deck.detect_format(decklist)

    eff_low, eff_high, land_target_label = deck.FORMAT_TARGETS[deck_format]

    # ------------------------------------------------------------------
    # 1. Load card data from cache (fetch any missing entries)
    # ------------------------------------------------------------------
    if verbose:
        print(f"Opening cache: {cache}")
    conn = sc.open_cache(Path(cache))

    txt_entries = deck.parse_decklist(decklist)
    if not txt_entries:
        print("No valid decklist entries found. Exiting.", file=sys.stderr)
        sys.exit(1)

    identifiers = [ident for _, ident in txt_entries]
    card_map = sc.load_decklist_cards(conn, identifiers, verbose=verbose)
    conn.close()
    if verbose:
        print()

    # ------------------------------------------------------------------
    # 1b. Identify the commander (first line of decklist)
    # ------------------------------------------------------------------
    commander_ident = txt_entries[0][1]
    commander_key = (commander_ident.set_code.lower(), commander_ident.collector_number.lower())
    commander_card = card_map.get(commander_key)

    if commander_card is None:
        print(
            f"ERROR: Commander card {commander_ident.name!r} not found in cache.",
            file=sys.stderr,
        )
        sys.exit(1)

    commander_name: str = commander_card.get("name", commander_ident.name)

    # Derive colour identity from commander
    colour_identity: set[str] = set(commander_card.get("color_identity", []))
    if not colour_identity:
        # Fallback: parse mana cost pips
        mc = commander_card.get("mana_cost") or ""
        colour_identity = {p for p in deck.SYMBOL_RE.findall(mc) if p in set(deck.WUBRG_ORDER)}
    colours: set[str] = colour_identity
    sorted_colours: list[str] = deck.sorted_colours(colours)

    # Derive synergy creature types from commander
    synergy_types: set[str] = deck.extract_synergy_types(commander_card)

    commander_cmc = commander_card.get("cmc", 0)

    # ------------------------------------------------------------------
    # 2. Expand by qty so Plains x2 counts as two land sources
    # ------------------------------------------------------------------
    expanded: list[dict] = []
    for qty, ident in txt_entries:
        key = (ident.set_code.lower(), ident.collector_number.lower())
        card = card_map.get(key)
        if card is None:
            print(
                f"WARNING: {ident.name} not in cache - skipping.",
                file=sys.stderr,
            )
            continue
        for _ in range(qty):
            expanded.append(card)

    total_cards = len(expanded)

    # ------------------------------------------------------------------
    # 3. Partition into lands and spells
    # ------------------------------------------------------------------
    lands = [c for c in expanded if deck.is_land(c)]
    spells = [c for c in expanded if not deck.is_land(c)]

    total_lands = len(lands)
    total_spells = len(spells)

    # ------------------------------------------------------------------
    # 3b. Type distribution
    # ------------------------------------------------------------------
    type_dist: Counter = Counter()
    for card in expanded:
        type_dist[deck.card_type_category(card)] += 1

    # ------------------------------------------------------------------
    # 4. Pip demand
    # ------------------------------------------------------------------
    pip_counts: Counter = Counter()
    needs_colour: Counter = Counter()

    for card in spells:
        mc = card.get("mana_cost") or ""
        if not mc:
            faces = card.get("card_faces", [])
            mc = " ".join(f.get("mana_cost", "") for f in faces)
        pips = deck.pip_colours(mc, colours)
        pip_counts.update(pips)
        for c in set(pips) & colours:
            needs_colour[c] += 1

    total_pips = sum(pip_counts.values())

    # ------------------------------------------------------------------
    # 5. Land colour sources & speed
    # ------------------------------------------------------------------
    source_count: Counter = Counter()
    speed_counts: Counter = Counter()

    for card in lands:
        for colour in deck.produced_mana(card) & colours:
            source_count[colour] += 1
        speed = deck.land_speed(card)
        speed_counts[speed] += 1

    # ------------------------------------------------------------------
    # 6. Mana rocks & creatures
    # ------------------------------------------------------------------
    rocks = [c for c in expanded if deck.is_mana_rock(c) and not deck.is_land(c)]
    mcreats = [
        c
        for c in expanded
        if deck.is_mana_creature(c) and not deck.is_land(c) and not deck.is_artifact(c)
    ]

    rock_total = sum(deck.rock_land_equiv(c) for c in rocks + mcreats)
    effective_land_count = total_lands + rock_total

    # ------------------------------------------------------------------
    # 7. Commander synergy targets
    # ------------------------------------------------------------------
    if synergy_types:
        synergy_targets = [
            c for c in expanded if deck.has_synergy_type(c, synergy_types) and not deck.is_land(c)
        ]
        non_synergy_creatures = [
            c
            for c in expanded
            if deck.is_creature(c)
            and not deck.is_land(c)
            and not deck.has_synergy_type(c, synergy_types)
        ]
    else:
        synergy_targets = []
        non_synergy_creatures = [c for c in expanded if deck.is_creature(c) and not deck.is_land(c)]

    # ------------------------------------------------------------------
    # 8. Mana curve
    # ------------------------------------------------------------------
    cmc_counter: Counter = Counter()
    for card in spells:
        cmc = card.get("cmc")
        if cmc is None:
            mc = card.get("mana_cost") or ""
            cmc = deck.card_cmc_from_cost(mc)
        cmc_counter[int(cmc)] += 1

    # ------------------------------------------------------------------
    # 9. Colour balance (computed once, reused by all output modes)
    # ------------------------------------------------------------------
    balance_data = deck.colour_balance(source_count, pip_counts, total_lands, total_pips, colours)

    return DeckStats(
        commander_name=commander_name,
        decklist=decklist,
        deck_format=deck_format,
        cache_path=cache,
        card_count=total_cards,
        sorted_colours=sorted_colours,
        colour_identity=colour_identity,
        synergy_types=synergy_types,
        commander_cmc=commander_cmc,
        lands=lands,
        spells=spells,
        total_lands=total_lands,
        total_spells=total_spells,
        type_distribution=type_dist,
        source_count=source_count,
        speed_counts=speed_counts,
        pip_counts=pip_counts,
        needs_colour=needs_colour,
        total_pips=total_pips,
        rocks=rocks,
        mana_creatures=mcreats,
        rock_total=rock_total,
        effective_land_count=effective_land_count,
        synergy_targets=synergy_targets,
        non_synergy_creatures=non_synergy_creatures,
        cmc_counter=cmc_counter,
        balance_data=balance_data,
        eff_low=eff_low,
        eff_high=eff_high,
        land_target_label=land_target_label,
        card_map_size=len(card_map),
    )


# ---------------------------------------------------------------------------
# Output: JSON / return_data
# ---------------------------------------------------------------------------


def _output_json(stats: DeckStats) -> dict:
    """Build the JSON-serialisable analysis dict."""
    out_data = {
        "type_distribution": dict(stats.type_distribution),
        "mana": {
            "raw": stats.total_lands,
            "effective": round(stats.effective_land_count, 1),
            "target_low": stats.eff_low,
            "target_high": stats.eff_high,
        },
        "speed": stats.speed_counts,
        "balance": {},
        "curve": {k: v for k, v in sorted(stats.cmc_counter.items())},
        "synergy": {"matches": len(set(c["name"] for c in stats.synergy_targets))}
        if stats.synergy_types
        else {},
    }
    for col in stats.sorted_colours:
        _src_pct, pip_pct, delta = stats.balance_data[col]
        bal = "OK" if abs(delta) < 15 else ("OVER" if delta > 0 else "UNDER")
        out_data["balance"][col] = {
            "source_count": stats.source_count[col],
            "pip_pct": round(pip_pct, 1),
            "status": bal,
        }
    return out_data


# ---------------------------------------------------------------------------
# Output: compact agent mode
# ---------------------------------------------------------------------------


def _output_agent(stats: DeckStats) -> None:
    """Print compact agent-mode output."""
    print(
        f"[Mana/Land] Raw:{stats.total_lands}, Eff:{stats.effective_land_count:.1f}, "
        f"Target:{stats.eff_low}-{stats.eff_high}"
    )
    print(
        f"[Speed] Untapped:{stats.speed_counts['untapped']}, Shock:{stats.speed_counts['shock']}, "
        f"Cond:{stats.speed_counts['conditional']}, Tapped:{stats.speed_counts['tapped']}"
    )
    b_str = []
    for col in stats.sorted_colours:
        _src_pct, pip_pct, delta = stats.balance_data[col]
        bal = "OK" if abs(delta) < 15 else ("OVER" if delta > 0 else "UNDER")
        b_str.append(
            f"{deck.COLOUR_LABELS.get(col, col)[0]}:{stats.source_count[col]}/{pip_pct:.1f}%({bal})"
        )
    print("[Balance] " + ", ".join(b_str))
    td = stats.type_distribution
    td_str = ", ".join(f"{k.title()}:{v}" for k, v in sorted(td.items()))
    print(f"[Composition] {td_str}")
    c_str = [f"{k}:{v}" for k, v in sorted(stats.cmc_counter.items())]
    print("[Curve] " + ", ".join(c_str))
    if stats.synergy_types:
        n_syn = len(set(c["name"] for c in stats.synergy_targets))
        print(f"[Synergy] Matches:{n_syn}")


# ---------------------------------------------------------------------------
# Verbose-output section helpers (all private, all take DeckStats)
# ---------------------------------------------------------------------------


def _print_header(stats: DeckStats) -> None:
    """Print the banner with commander name, format, colours, and card counts."""
    synergy_label = (
        "/".join(t.title() for t in sorted(stats.synergy_types))
        if stats.synergy_types
        else "none detected"
    )

    print("=" * 72)
    print(f"{stats.commander_name.upper()} - FULL MANA & LAND ANALYSIS")
    print(f"  Decklist : {stats.decklist}")
    print(f"  Format   : {stats.deck_format}")
    print(f"  Cache    : {stats.cache_path}  ({stats.card_map_size} unique cards)")
    print(
        f"  Colours  : {' '.join(stats.sorted_colours)} "
        f"({', '.join(deck.COLOUR_LABELS.get(c, c) for c in stats.sorted_colours)})"
    )
    print(f"  Synergy  : {synergy_label}")
    print("=" * 72)
    print()
    print(f"  Total cards      : {stats.card_count}")
    print(f"  Lands            : {stats.total_lands}  (target {stats.land_target_label})")
    print(f"  Effective lands  : {stats.effective_land_count:.1f}  (lands + rock equivalents)")
    print(f"  Spells           : {stats.total_spells}")
    print()


def _print_composition(stats: DeckStats) -> None:
    """Print deck type distribution."""
    print_separator("DECK COMPOSITION")
    display_order = [
        "creature",
        "instant",
        "sorcery",
        "artifact",
        "enchantment",
        "planeswalker",
        "battle",
        "land",
    ]
    for cat in display_order:
        count = stats.type_distribution.get(cat, 0)
        if count:
            print(f"  {cat.title():<16} {count:>3}")
    other = stats.type_distribution.get("other", 0)
    if other:
        print(f"  {'Other':<16} {other:>3}")
    print(f"  {'─' * 20}")
    print(f"  {'Total':<16} {stats.card_count:>3}")
    print()


def _print_balance(stats: DeckStats) -> None:
    """Print the LAND COLOUR SOURCES table."""
    print_separator("LAND COLOUR SOURCES")
    print(f"  {'Colour':<8} {'Sources':>7}  {'% of lands':>10}  {'Pip demand':>10}  {'Balance'}")
    print(f"  {'-' * 8} {'-' * 7}  {'-' * 10}  {'-' * 10}  {'-' * 12}")
    for col in stats.sorted_colours:
        src_pct, pip_pct, delta = stats.balance_data[col]
        balance = "OK" if abs(delta) < 15 else ("OVER" if delta > 0 else "UNDER")
        print(
            f"  {deck.COLOUR_LABELS.get(col, col):<8} {stats.source_count[col]:>7}  "
            f"{src_pct:>9.1f}%  {pip_pct:>9.1f}%  {balance}"
        )
    print()


def _print_speed(stats: DeckStats, *, compact: bool) -> None:
    """Print the LAND SPEED BREAKDOWN section with counts and optional detail table."""
    colours = stats.colour_identity
    print_separator("LAND SPEED BREAKDOWN")
    untapped_count = stats.speed_counts["untapped"]
    shock_count = stats.speed_counts["shock"]
    cond_count = stats.speed_counts["conditional"]
    tapped_count = stats.speed_counts["tapped"]
    print(f"  Always tapped          : {tapped_count}")
    print(f"  Conditional (check/fast/filter/verge): {cond_count}")
    print(f"  Shock (pay 2 life)     : {shock_count}")
    print(f"  Reliably untapped      : {untapped_count}")
    print()
    if not compact:
        print("  Land detail:")
        print(f"  {'Name':<35} {'Produces':<14} {'Speed'}")
        print(f"  {'-' * 35} {'-' * 14} {'-' * 12}")
        seen_land_names: set[str] = set()
        for card in stats.lands:
            name = card.get("name", "?")
            if name in seen_land_names:
                continue
            seen_land_names.add(name)
            prod = "".join(sorted(deck.produced_mana(card) & colours)) or "C"
            speed = deck.land_speed(card)
            cycling = "  [cycling]" if deck.CYCLING_RE.search(deck.oracle_text(card)) else ""
            print(f"  {name:<35} {'{' + prod + '}':<14} {speed}{cycling}")
        print()


def _print_ramp(stats: DeckStats, *, compact: bool) -> None:
    """Print the NON-LAND MANA SOURCES section with rocks and creatures tables."""
    print_separator("NON-LAND MANA SOURCES")
    if not compact:
        if stats.rocks:
            print("  Mana rocks (artifacts):")
            print(f"  {'Name':<35} {'CMC':>4}  {'Produces':<14} {'Land equiv':>10}  Notes")
            print(f"  {'-' * 35} {'-' * 4}  {'-' * 14} {'-' * 10}  {'-' * 20}")
            for card in stats.rocks:
                name = card.get("name", "?")
                cmc = card.get("cmc", 0)
                prod = deck.produced_mana(card)
                prod_str = "{" + "".join(sorted(prod)) + "}" if prod else "{?}"
                equiv = deck.rock_land_equiv(card)
                # First oracle line mentioning Add as a short note
                note = ""
                for line in deck.oracle_text(card).splitlines():
                    if deck.ROCK_TAP_RE.search(line):
                        note = line.strip()[:40]
                        break
                print(f"  {name:<35} {int(cmc):>4}  {prod_str:<14} {equiv:>10.1f}  {note}")
            print()

        if stats.mana_creatures:
            print("  Mana creatures:")
            print(f"  {'Name':<35} {'CMC':>4}  {'Produces':<14} {'Land equiv':>10}")
            print(f"  {'-' * 35} {'-' * 4}  {'-' * 14} {'-' * 10}")
            for card in stats.mana_creatures:
                name = card.get("name", "?")
                cmc = card.get("cmc", 0)
                prod = deck.produced_mana(card)
                prod_str = "{" + "".join(sorted(prod)) + "}" if prod else "{?}"
                equiv = deck.rock_land_equiv(card)
                print(f"  {name:<35} {int(cmc):>4}  {prod_str:<14} {equiv:>10.1f}")
            print()

    print(f"  Rock land-equiv total  : {stats.rock_total:.1f}")
    print()


def _print_recommendation(stats: DeckStats, *, compact: bool) -> None:
    """Print the EFFECTIVE MANA SOURCES & LAND COUNT RECOMMENDATION section."""
    colours = stats.colour_identity
    print_separator("EFFECTIVE MANA SOURCES & LAND COUNT RECOMMENDATION")
    print(f"  Raw land count           : {stats.total_lands}")
    print(f"  Rock/creature equivalents: +{stats.rock_total:.1f}")
    print(f"  Effective land count     : {stats.effective_land_count:.1f}")
    print(f"  Target range             : {stats.eff_low}-{stats.eff_high}")
    print()

    if stats.effective_land_count < stats.eff_low:
        shortage = stats.eff_low - stats.effective_land_count
        print(f"  !  BELOW target - add ~{shortage:.0f} land(s) or faster ramp.")
    elif stats.effective_land_count <= stats.eff_high:
        cushion = stats.effective_land_count - stats.eff_low
        print("  *  Within target range.")
        if cushion >= 1.0:
            print(f"     {cushion:.1f} equiv of headroom - cutting 1 raw land is reasonable.")
    else:
        excess = stats.effective_land_count - stats.eff_high
        print(f"  !  ABOVE target - can safely cut ~{excess:.0f} raw land(s).")
    print()

    # Weakest land candidates derived from speed data, not a hardcoded list
    if not compact:
        always_tapped = [c for c in stats.lands if deck.land_speed(c) == "tapped"]
        if always_tapped:
            print("  Always-tapped lands (weakest cut candidates):")
            seen: set[str] = set()
            for card in always_tapped:
                name = card.get("name", "?")
                if name in seen:
                    continue
                seen.add(name)
                prod = "".join(sorted(deck.produced_mana(card) & colours)) or "C"
                cycling = (
                    "  [has cycling]" if deck.CYCLING_RE.search(deck.oracle_text(card)) else ""
                )
                print(f"    * {name:<30} produces {{{prod}}}{cycling}")
    print()


def _print_synergy(stats: DeckStats, *, compact: bool) -> None:
    """Print the synergy/creature section."""
    if stats.synergy_types:
        synergy_title = (
            "COMMANDER SYNERGY CREATURES ("
            + ", ".join(t.title() for t in sorted(stats.synergy_types))
            + ")"
        )
    else:
        synergy_title = "CREATURES IN DECK"
    print_separator(synergy_title)
    if not compact:
        print(f"  {'Card':<35} {'Relevant types':<20} {'CMC':>4}  {'Synergy match'}")
        print(f"  {'-' * 35} {'-' * 20} {'-' * 4}  {'-' * 14}")

        all_creatures_for_table = stats.synergy_targets + stats.non_synergy_creatures
        unique_creatures = list(
            dict.fromkeys(
                c["name"]
                for c in sorted(all_creatures_for_table, key=lambda c: c.get("name", ""))
                if deck.is_creature(c) and not deck.is_land(c)
            )
        )
        for name in unique_creatures:
            card = next(c for c in all_creatures_for_table if c.get("name") == name)
            subtypes = deck.card_subtypes(card)
            cmc = card.get("cmc", 0)
            if stats.synergy_types:
                match_str = "YES" if deck.has_synergy_type(card, stats.synergy_types) else "NO"
                relevant = (
                    ", ".join(sorted(subtypes & (stats.synergy_types | {"changeling"}))) or "-"
                )
            else:
                match_str = "-"
                relevant = ", ".join(sorted(subtypes)) or "-"
            print(f"  {name:<35} {relevant:<20} {int(cmc):>4}  {match_str}")

        print()
    if stats.synergy_types:
        n_synergy = len(set(c["name"] for c in stats.synergy_targets))
        synergy_type_names = "/".join(t.title() for t in sorted(stats.synergy_types))
        print(f"  Synergy matches ({synergy_type_names}): {n_synergy}")
    print()


def _print_demand(stats: DeckStats) -> None:
    """Print the PIP DEMAND SUMMARY and MANA CURVE sections."""
    print_separator("PIP DEMAND SUMMARY")
    print(f"  {'Colour':<8} {'Pips':>5}  {'Share':>6}  {'Cards needing it':>18}")
    print(f"  {'-' * 8} {'-' * 5}  {'-' * 6}  {'-' * 18}")
    for col in stats.sorted_colours:
        pct = stats.pip_counts[col] / stats.total_pips * 100 if stats.total_pips else 0
        print(
            f"  {deck.COLOUR_LABELS.get(col, col):<8} {stats.pip_counts[col]:>5}  "
            f"{pct:>5.1f}%  {stats.needs_colour[col]:>18}"
        )
    print(f"  {'Total':<8} {stats.total_pips:>5}")
    print()

    print_separator("MANA CURVE (spells only)")
    for cmc_val in sorted(stats.cmc_counter):
        bar = "#" * stats.cmc_counter[cmc_val]
        print(f"  CMC {cmc_val:>2}: {stats.cmc_counter[cmc_val]:>2}  {bar}")
    print()


def _print_assessment(stats: DeckStats) -> None:
    """Print the OVERALL ASSESSMENT with issues and positives."""
    print_separator("OVERALL ASSESSMENT")
    issues: list[str] = []
    positives: list[str] = []

    if stats.eff_low <= stats.effective_land_count <= stats.eff_high:
        positives.append(
            f"Effective land count {stats.effective_land_count:.1f} "
            f"(raw {stats.total_lands} + {stats.rock_total:.1f} rock equiv) "
            f"is within target ({stats.eff_low}-{stats.eff_high})."
        )
    elif stats.effective_land_count < stats.eff_low:
        issues.append(
            f"Effective land count {stats.effective_land_count:.1f} is below target "
            f"({stats.eff_low}-{stats.eff_high}). Add ramp or lands."
        )
    else:
        issues.append(
            f"Effective land count {stats.effective_land_count:.1f} is above target "
            f"({stats.eff_low}-{stats.eff_high}). Consider cutting 1-2 raw lands."
        )

    for col in stats.sorted_colours:
        _src_pct, pip_pct, delta = stats.balance_data[col]
        label = deck.COLOUR_LABELS.get(col, col)
        if abs(delta) < 15:
            positives.append(
                f"{label} sources ({stats.source_count[col]}) well matched "
                f"to pip demand ({stats.pip_counts[col]} pips, {pip_pct:.0f}%)."
            )
        elif delta > 0:
            issues.append(
                f"{label} may be over-supplied ({stats.source_count[col]} sources "
                f"vs {pip_pct:.0f}% demand)."
            )
        else:
            issues.append(
                f"{label} may be under-supplied ({stats.source_count[col]} sources "
                f"vs {pip_pct:.0f}% demand)."
            )

    untapped_count = stats.speed_counts["untapped"]
    shock_count = stats.speed_counts["shock"]
    reliable_untapped = untapped_count + shock_count
    if reliable_untapped >= 10:
        positives.append(
            f"{reliable_untapped} reliably untapped lands "
            f"({untapped_count} always + {shock_count} shock) - "
            f"strong for a {int(stats.commander_cmc)}-drop commander."
        )
    else:
        issues.append(f"Only {reliable_untapped} reliably untapped lands - risk of slow starts.")

    if stats.synergy_types:
        n_synergy = len(set(c["name"] for c in stats.synergy_targets))
        synergy_type_names = "/".join(t.title() for t in sorted(stats.synergy_types))
        if n_synergy >= 15:
            positives.append(
                f"{n_synergy} {synergy_type_names} synergy targets - plenty of threats."
            )
        elif n_synergy >= 10:
            positives.append(f"{n_synergy} {synergy_type_names} synergy targets - adequate.")
        else:
            issues.append(
                f"Only {n_synergy} {synergy_type_names} synergy targets - "
                f"consider adding more creatures with those types."
            )

    if stats.rocks or stats.mana_creatures:
        positives.append(
            f"{len(stats.rocks)} mana rock(s) + {len(stats.mana_creatures)} mana creature(s) "
            f"({stats.rock_total:.1f} land-equiv total) - good for consistency."
        )
    else:
        issues.append("No mana rocks or mana creatures found - add ramp.")

    print("  Positives:")
    for p in positives:
        print(f"    * {p}")
    print()
    if issues:
        print("  Flags:")
        for i in issues:
            print(f"    ! {i}")
    else:
        print("  No significant issues found.")
    print()
    print("=" * 72)


# ---------------------------------------------------------------------------
# Output: full human-readable analysis
# ---------------------------------------------------------------------------


def _output_verbose(stats: DeckStats, *, compact: bool) -> None:
    """Print the full human-readable analysis."""
    _print_header(stats)
    _print_composition(stats)
    _print_balance(stats)
    _print_speed(stats, compact=compact)
    _print_ramp(stats, compact=compact)
    _print_recommendation(stats, compact=compact)
    _print_synergy(stats, compact=compact)
    _print_demand(stats)
    _print_assessment(stats)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run(
    decklist: str,
    cache: str = str(DB_PATH),
    fmt: str | None = None,
    compact: bool = False,
    agent: bool = False,
    json_flag: bool = False,
    return_data: bool = False,
) -> dict | None:
    """Run the full mana-base and deck analysis, printing results to stdout."""
    verbose = not (agent or json_flag)
    stats = _compute_stats(decklist, cache, fmt, verbose)

    if json_flag or return_data:
        out = _output_json(stats)
        if return_data:
            return out
        import json

        print(json.dumps(out))
        return None

    if agent:
        _output_agent(stats)
        return None

    _output_verbose(stats, compact=compact)
    return None
