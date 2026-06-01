"""Opening-hand simulator for decklists.

Provides single-hand draws and Monte-Carlo aggregate statistics for
mulligan, land-density, and curve evaluation. The commander is held in
the command zone for singleton formats (Brawl, Commander) and excluded
from the shuffled library so opener stats reflect real play.

Pure data in, pure data out for the helpers; ``run`` handles I/O and
output formatting (rich or JSON) for the CLI.
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from manascope import scryfall as sc
from manascope.deck import (
    CardIdentifier,
    card_type_category,
    detect_format,
    is_land,
    parse_decklist,
)

# Standard MTG opening-hand size. Exposed as a constant for tests.
DEFAULT_HAND_SIZE = 7
# Mulligan cap: you can't mulligan past a 1-card hand under London rules,
# so 6 mulligans is the theoretical maximum (7 -> 6 -> 5 -> ... -> 1).
DEFAULT_MAX_MULLIGANS = 6


@dataclass
class SingleHand:
    """One simulated opener plus the cards drawn during ``play_to`` turns."""

    hand: list[dict]
    drawn_after: list[dict]
    mulligans: int
    cards_bottomed: int


@dataclass
class AggregateStats:
    """Monte-Carlo aggregate over N simulated openers."""

    trials: int
    hand_size: int
    play_to: int
    mulligan_to: int | None
    avg_lands_in_opener: float
    avg_spell_cmc: float
    avg_mulligans: float
    land_distribution: dict[int, int]
    mulligan_distribution: dict[int, int]
    type_counts_per_hand: dict[str, float]
    p_keepable_opener: float
    library_size: int
    commander_name: str | None = None
    library_lands: int = 0
    library_spells: int = 0
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pure helpers (no I/O)
# ---------------------------------------------------------------------------


def build_library(
    entries: list[tuple[int, CardIdentifier]],
    card_map: dict[tuple[str, str], dict],
) -> tuple[list[dict], dict | None]:
    """Expand a parsed decklist into a shuffled-able library.

    The first parsed entry is treated as the commander (per the rest of
    the codebase) and *one* copy is removed from the library so it sits
    in the command zone. Entries whose cards aren't in the supplied
    ``card_map`` are silently skipped — callers should pre-load the
    cache via :func:`manascope.scryfall.load_decklist_cards`.

    Returns ``(library, commander_card)``. ``commander_card`` is ``None``
    when the first entry isn't resolvable from the cache.
    """
    library: list[dict] = []
    commander_card: dict | None = None
    for index, (qty, ident) in enumerate(entries):
        key = (ident.set_code.lower(), ident.collector_number.lower())
        card = card_map.get(key)
        if card is None:
            continue
        if index == 0:
            commander_card = card
            copies = max(0, qty - 1)
        else:
            copies = qty
        for _ in range(copies):
            library.append(card)
    return library, commander_card


def hand_summary(hand: list[dict]) -> dict:
    """Return per-hand stats: lands, spells, type counts, avg spell CMC."""
    lands = sum(1 for c in hand if is_land(c))
    types = Counter(card_type_category(c) for c in hand)
    cmcs = [float(c.get("cmc", 0.0) or 0.0) for c in hand if not is_land(c)]
    avg_cmc = sum(cmcs) / len(cmcs) if cmcs else 0.0
    return {
        "lands": lands,
        "spells": len(hand) - lands,
        "type_counts": dict(types),
        "avg_spell_cmc": avg_cmc,
    }


def decide_keep(hand: list[dict], mulligan_to: int | None) -> bool:
    """Default keep heuristic: keep iff lands ∈ [2, mulligan_to].

    When ``mulligan_to`` is ``None`` every hand is kept (no mulligans).
    The 2-land floor matches conventional Brawl/Commander wisdom; the
    upper bound is the user-supplied ceiling.
    """
    if mulligan_to is None:
        return True
    lands = sum(1 for c in hand if is_land(c))
    return 2 <= lands <= mulligan_to


def simulate_one(
    library: list[dict],
    *,
    hand_size: int = DEFAULT_HAND_SIZE,
    play_to: int = 0,
    mulligan_to: int | None = None,
    max_mulligans: int = DEFAULT_MAX_MULLIGANS,
    rng: random.Random | None = None,
) -> SingleHand:
    """Simulate one opener with London-mulligan rules.

    After ``N`` mulligans we keep ``hand_size - N`` cards (bottoming the
    rest). ``play_to`` extra cards are drawn after the keep decision to
    simulate the first N turns. ``rng`` is injectable for reproducibility
    and tests.
    """
    if rng is None:
        rng = random.Random()
    if not library:
        return SingleHand(hand=[], drawn_after=[], mulligans=0, cards_bottomed=0)

    mulligans = 0
    while True:
        shuffled = list(library)
        rng.shuffle(shuffled)
        opener_window = shuffled[:hand_size]
        # Keep decision uses the full opener_window (London: you see 7 every time).
        keep = decide_keep(opener_window, mulligan_to) or mulligans >= max_mulligans
        if not keep:
            mulligans += 1
            continue
        kept_size = max(1, hand_size - mulligans)
        kept = opener_window[:kept_size]
        # The rest of the opener_window beyond kept_size goes to the bottom
        # (we don't track order). Subsequent draws come from shuffled[hand_size:].
        extra = shuffled[hand_size : hand_size + play_to]
        return SingleHand(
            hand=kept,
            drawn_after=extra,
            mulligans=mulligans,
            cards_bottomed=hand_size - kept_size,
        )


def aggregate(
    library: list[dict],
    *,
    trials: int,
    hand_size: int = DEFAULT_HAND_SIZE,
    play_to: int = 0,
    mulligan_to: int | None = None,
    max_mulligans: int = DEFAULT_MAX_MULLIGANS,
    rng: random.Random | None = None,
) -> AggregateStats:
    """Run ``trials`` simulations and return aggregate statistics."""
    if rng is None:
        rng = random.Random()

    land_dist: Counter[int] = Counter()
    mull_dist: Counter[int] = Counter()
    type_totals: Counter[str] = Counter()
    total_lands = 0
    total_spells = 0
    total_cmc_weighted = 0.0
    keepable = 0

    for _ in range(trials):
        result = simulate_one(
            library,
            hand_size=hand_size,
            play_to=play_to,
            mulligan_to=mulligan_to,
            max_mulligans=max_mulligans,
            rng=rng,
        )
        summary = hand_summary(result.hand)
        land_dist[summary["lands"]] += 1
        mull_dist[result.mulligans] += 1
        total_lands += summary["lands"]
        total_spells += summary["spells"]
        total_cmc_weighted += summary["avg_spell_cmc"] * summary["spells"]
        for t, n in summary["type_counts"].items():
            type_totals[t] += n
        # "Keepable" = the post-mulligan hand had 2-5 lands; useful even
        # when the user didn't pass --mulligan-to.
        if 2 <= summary["lands"] <= 5:
            keepable += 1

    avg_lands = total_lands / trials if trials else 0.0
    avg_cmc = total_cmc_weighted / total_spells if total_spells else 0.0
    avg_mulls = sum(k * v for k, v in mull_dist.items()) / trials if trials else 0.0
    library_lands = sum(1 for c in library if is_land(c))

    return AggregateStats(
        trials=trials,
        hand_size=hand_size,
        play_to=play_to,
        mulligan_to=mulligan_to,
        avg_lands_in_opener=round(avg_lands, 3),
        avg_spell_cmc=round(avg_cmc, 3),
        avg_mulligans=round(avg_mulls, 3),
        land_distribution={k: land_dist.get(k, 0) for k in range(hand_size + 1)},
        mulligan_distribution={k: mull_dist.get(k, 0) for k in range(max_mulligans + 1)},
        type_counts_per_hand={t: round(n / trials, 3) for t, n in type_totals.items()},
        p_keepable_opener=round(keepable / trials, 4) if trials else 0.0,
        library_size=len(library),
        library_lands=library_lands,
        library_spells=len(library) - library_lands,
    )


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------


def _card_brief(card: dict) -> dict:
    return {
        "name": card.get("name"),
        "mana_cost": card.get("mana_cost") or "",
        "cmc": card.get("cmc", 0),
        "type_line": card.get("type_line", ""),
        "is_land": is_land(card),
    }


def _agent_single_line(
    result: SingleHand,
    index: int | None = None,
) -> str:
    """Render one hand as a single dense line for agent consumption.

    Format::

        hand[1] mulls=0 lands=2/5 cmc=3.2 names=Card A|Card B|Card C

    The ``names`` list preserves draw order; types/costs are omitted because
    the agent can re-derive them from a single ``lookup --brief --json`` call
    if needed (per AGENTS.md).
    """
    summary = hand_summary(result.hand)
    idx = f"[{index}] " if index is not None else ""
    names = "|".join(c.get("name", "?") for c in result.hand)
    return (
        f"hand{idx}mulls={result.mulligans} "
        f"lands={summary['lands']}/{len(result.hand)} "
        f"cmc={summary['avg_spell_cmc']:.2f} "
        f"names={names}"
    )


def _agent_aggregate_line(stats: AggregateStats) -> str:
    """One-line aggregate summary for agent consumption."""
    return (
        f"agg trials={stats.trials} lib={stats.library_size} "
        f"avg_lands={stats.avg_lands_in_opener} "
        f"keepable={stats.p_keepable_opener:.1%} "
        f"avg_mulls={stats.avg_mulligans} "
        f"cmc={stats.avg_spell_cmc}"
    )


def _render_single(
    result: SingleHand,
    commander_card: dict | None,
    deck_format: str,
    library_size: int,
    *,
    json_flag: bool,
    agent: bool = False,
) -> None:
    if agent:
        print(_agent_single_line(result))
        return
    if json_flag:
        payload = {
            "format": deck_format,
            "commander": commander_card.get("name") if commander_card else None,
            "library_size": library_size,
            "mulligans": result.mulligans,
            "cards_bottomed": result.cards_bottomed,
            "hand": [_card_brief(c) for c in result.hand],
            "drawn_after": [_card_brief(c) for c in result.drawn_after],
            "summary": hand_summary(result.hand),
        }
        print(json.dumps(payload))
        return

    if commander_card:
        print(f"Command zone: {commander_card.get('name')}")
    print(f"Library: {library_size} cards | Mulligans taken: {result.mulligans}")
    if result.cards_bottomed:
        print(f"Bottomed: {result.cards_bottomed} card(s) under London mulligan")
    summary = hand_summary(result.hand)
    print(f"\nOpening hand ({len(result.hand)} cards, {summary['lands']} lands):")
    for c in result.hand:
        cost = (c.get("mana_cost") or "").ljust(12)
        print(f"  {cost} {c.get('name', '?'):32}  {c.get('type_line', '')}")
    if result.drawn_after:
        print(f"\nDraws (next {len(result.drawn_after)} turns):")
        for c in result.drawn_after:
            cost = (c.get("mana_cost") or "").ljust(12)
            print(f"  {cost} {c.get('name', '?'):32}  {c.get('type_line', '')}")


def _render_aggregate(
    stats: AggregateStats,
    commander_card: dict | None,
    deck_format: str,
    *,
    json_flag: bool,
    agent: bool = False,
) -> None:
    if agent:
        print(_agent_aggregate_line(stats))
        return
    if json_flag:
        payload = {
            "format": deck_format,
            "commander": commander_card.get("name") if commander_card else None,
            "trials": stats.trials,
            "hand_size": stats.hand_size,
            "play_to": stats.play_to,
            "mulligan_to": stats.mulligan_to,
            "library_size": stats.library_size,
            "library_lands": stats.library_lands,
            "library_spells": stats.library_spells,
            "avg_lands_in_opener": stats.avg_lands_in_opener,
            "avg_spell_cmc": stats.avg_spell_cmc,
            "avg_mulligans": stats.avg_mulligans,
            "p_keepable_opener": stats.p_keepable_opener,
            "land_distribution": stats.land_distribution,
            "mulligan_distribution": stats.mulligan_distribution,
            "type_counts_per_hand": stats.type_counts_per_hand,
        }
        print(json.dumps(payload))
        return

    name = commander_card.get("name") if commander_card else "(no commander)"
    print(f"Commander: {name} | Format: {deck_format}")
    print(
        f"Library: {stats.library_size} ({stats.library_lands} lands / "
        f"{stats.library_spells} spells)"
    )
    print(f"Trials: {stats.trials} | Hand: {stats.hand_size} | Play-to turn: {stats.play_to}")
    if stats.mulligan_to is not None:
        print(f"Mulligan policy: keep iff 2 <= lands <= {stats.mulligan_to}")
    else:
        print("Mulligan policy: keep every hand")
    print()
    print(f"Avg lands in opener:    {stats.avg_lands_in_opener:.2f}")
    print(f"Avg spell CMC:          {stats.avg_spell_cmc:.2f}")
    print(f"Avg mulligans taken:    {stats.avg_mulligans:.2f}")
    print(f"P(2-5 lands in opener): {stats.p_keepable_opener:.1%}")
    print("\nLand-count distribution:")
    max_count = max(stats.land_distribution.values()) if stats.land_distribution else 1
    for k in sorted(stats.land_distribution):
        count = stats.land_distribution[k]
        bar = "#" * int(40 * count / max_count) if max_count else ""
        pct = 100 * count / stats.trials if stats.trials else 0.0
        print(f"  {k} lands: {count:>6} ({pct:5.1f}%)  {bar}")
    if stats.mulligan_to is not None:
        print("\nMulligan distribution:")
        for k in sorted(stats.mulligan_distribution):
            count = stats.mulligan_distribution[k]
            if count == 0:
                continue
            pct = 100 * count / stats.trials if stats.trials else 0.0
            print(f"  {k} mulls: {count:>6} ({pct:5.1f}%)")


def _render_many(
    results: list[SingleHand],
    commander_card: dict | None,
    deck_format: str,
    library_size: int,
    *,
    json_flag: bool,
    agent: bool,
) -> None:
    """Render N independent opening hands (not aggregate stats).

    Agent mode prints one dense line per hand. JSON mode emits a single
    array of per-hand objects. Rich mode delegates to the single-hand
    renderer per result with a header separator.
    """
    if agent:
        for i, r in enumerate(results, 1):
            print(_agent_single_line(r, index=i))
        return
    if json_flag:
        payload = {
            "format": deck_format,
            "commander": commander_card.get("name") if commander_card else None,
            "library_size": library_size,
            "hands": [
                {
                    "index": i,
                    "mulligans": r.mulligans,
                    "cards_bottomed": r.cards_bottomed,
                    "summary": hand_summary(r.hand),
                    "names": [c.get("name") for c in r.hand],
                }
                for i, r in enumerate(results, 1)
            ],
        }
        print(json.dumps(payload))
        return
    for i, r in enumerate(results, 1):
        print(f"=== Hand {i} ===")
        _render_single(r, commander_card, deck_format, library_size, json_flag=False, agent=False)
        print()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def run(
    decklist: str,
    cache: Path,
    *,
    fmt: str | None = None,
    trials: int = 1,
    hands: int = 1,
    play_to: int = 0,
    mulligan_to: int | None = None,
    seed: int | None = None,
    json_flag: bool = False,
    agent: bool = False,
    strict: bool = False,
) -> None:
    """Simulate opening hands for the given decklist and print the result.

    Three modes, selected by argument:

    * ``hands > 1``  — render N individual hands (each via ``simulate_one``);
      ``--agent`` prints a dense one-liner per hand.
    * ``trials > 1`` — Monte-Carlo aggregate statistics; ``--agent`` prints
      a single summary line.
    * otherwise     — render a single hand.

    ``hands`` and ``trials`` are mutually exclusive at the CLI layer (the
    Typer command rejects passing both > 1).
    """
    deck_format = fmt if fmt else detect_format(decklist)
    rng = random.Random(seed)

    entries = parse_decklist(decklist, strict=strict)
    if not entries:
        print("No valid decklist entries found.", file=sys.stderr)
        sys.exit(1)

    conn = sc.open_cache(cache)
    try:
        card_map = sc.load_decklist_cards(conn, [ident for _, ident in entries], verbose=False)
    finally:
        conn.close()

    library, commander_card = build_library(entries, card_map)
    if not library:
        print(
            "Library is empty after loading decklist; ensure the Scryfall cache is primed.",
            file=sys.stderr,
        )
        sys.exit(1)

    if hands > 1:
        results = [
            simulate_one(library, play_to=play_to, mulligan_to=mulligan_to, rng=rng)
            for _ in range(hands)
        ]
        _render_many(
            results,
            commander_card,
            deck_format,
            library_size=len(library),
            json_flag=json_flag,
            agent=agent,
        )
        return

    if trials <= 1:
        result = simulate_one(
            library,
            play_to=play_to,
            mulligan_to=mulligan_to,
            rng=rng,
        )
        _render_single(
            result,
            commander_card,
            deck_format,
            library_size=len(library),
            json_flag=json_flag,
            agent=agent,
        )
        return

    stats = aggregate(
        library,
        trials=trials,
        play_to=play_to,
        mulligan_to=mulligan_to,
        rng=rng,
    )
    _render_aggregate(stats, commander_card, deck_format, json_flag=json_flag, agent=agent)
