"""Typer-based CLI entry point for the manascope toolkit.

Each subcommand (analyze, review, pipeline, prime, verify, lookup, edhrec)
delegates to a sibling module for the actual work; this module only handles
argument parsing, output routing, and exit codes.

Usage:
    uv run manascope analyze --decklist decks/commander/my_deck.txt
    uv run manascope review  --decklist decks/commander/my_deck.txt \
        --collection collections/my_collection.csv
    uv run manascope prime   "Kaalia of the Vast"
    uv run manascope verify  --decklist decks/commander/my_deck.txt \
        --collection collections/my_collection.csv
    uv run manascope lookup  "Sol Ring" "Kaalia of the Vast"
    uv run manascope edhrec  "Kaalia of the Vast"
"""

import contextlib
import io
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from manascope import DB_PATH, __version__

_notice_console = Console(stderr=True)


def _print_notice() -> None:
    """Print the unofficial fan project notice to stderr, only when stderr is a TTY."""
    if not _notice_console.is_terminal:
        return
    _notice_console.print(
        "ManaScope is an unofficial fan project · Data from Scryfall & EDHREC · "
        "Not affiliated with Wizards of the Coast, Scryfall, or EDHREC",
        style="yellow",
    )


app = typer.Typer(
    name="manascope",
    help="MTG deck analysis toolkit - mana base, EDHREC review, collection verification.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"manascope {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            help="Show version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """MTG deck analysis toolkit."""
    _print_notice()


CachePath = Annotated[Path, typer.Option("--cache", help="Path to SQLite cache database.")]


# Analyze


@app.command()
def analyze(
    decklist: Annotated[str, typer.Option(help="Path to the decklist .txt file.")],
    fmt: Annotated[
        str | None,
        typer.Option("--format", help="Override format (commander|brawl|standardbrawl)."),
    ] = None,
    compact: Annotated[
        bool, typer.Option("--compact", help="Omit per-card detail tables.")
    ] = False,
    agent: Annotated[
        bool, typer.Option("--agent", help="Output dense machine-readable format.")
    ] = False,
    json_flag: Annotated[bool, typer.Option("--json", help="Output pure JSON format.")] = False,
    cache: CachePath = DB_PATH,
) -> None:
    """Full mana-base and deck analysis."""
    from manascope.analyze import run

    run(
        decklist=decklist,
        cache=str(cache),
        fmt=fmt,
        compact=compact,
        agent=agent,
        json_flag=json_flag,
    )


# Review


@app.command()
def review(
    decklist: Annotated[str, typer.Option(help="Path to the decklist .txt file.")],
    collection: Annotated[str | None, typer.Option(help="Path to collection CSV path.")] = None,
    top: Annotated[int, typer.Option(help="Number of EDHREC cards to evaluate.")] = 80,
    fmt: Annotated[str | None, typer.Option("--format", help="Override format.")] = None,
    no_candidates: Annotated[
        bool,
        typer.Option("--no-candidates", help="Skip owned upgrade candidates section."),
    ] = False,
    compact: Annotated[bool, typer.Option("--compact", help="Reduce decorative output.")] = False,
    agent: Annotated[
        bool, typer.Option("--agent", help="Output dense machine-readable format.")
    ] = False,
    json_flag: Annotated[bool, typer.Option("--json", help="Output pure JSON format.")] = False,
    cache: CachePath = DB_PATH,
) -> None:
    """EDHREC cross-reference and owned-card gap analysis."""
    from manascope.review import run

    run(
        decklist=decklist,
        collection=collection,
        top=top,
        fmt=fmt,
        no_candidates=no_candidates,
        compact=compact,
        agent=agent,
        json_flag=json_flag,
        cache=str(cache),
    )


# Pipeline


@app.command()
def pipeline(
    decklist: Annotated[str, typer.Option(help="Path to the decklist .txt file.")],
    collection: Annotated[str | None, typer.Option(help="Path to collection CSV path.")] = None,
    fmt: Annotated[
        str | None,
        typer.Option("--format", help="Override format (commander|brawl|standardbrawl)."),
    ] = None,
    top: Annotated[int, typer.Option(help="Number of EDHREC cards to evaluate.")] = 80,
    cache: CachePath = DB_PATH,
) -> None:
    """Run a combined JSON pipeline analysis for AI agents."""
    import json

    from manascope.analyze import run as run_analyze
    from manascope.review import run as run_review

    analyze_data = run_analyze(
        decklist=decklist, cache=str(cache), fmt=fmt, return_data=True, json_flag=True
    )

    review_data = run_review(
        decklist=decklist,
        collection=collection,
        top=top,
        fmt=fmt,
        no_candidates=True,
        cache=str(cache),
        return_data=True,
        json_flag=True,
    )

    combined = {
        "analyze": analyze_data,
        "review": review_data,
    }

    print(json.dumps(combined))


# Prime


@app.command()
def prime(
    name: Annotated[str, typer.Argument(help="Commander name (display name or slug).")],
    top: Annotated[int, typer.Option(help="Number of EDHREC cards to evaluate.")] = 80,
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Suppress per-card messages.")
    ] = False,
    cache: CachePath = DB_PATH,
) -> None:
    """Prime the Scryfall cache with EDHREC-recommended cards."""
    from manascope import edhrec as ec
    from manascope import scryfall as sc

    def _suppress_stdout():
        return contextlib.redirect_stdout(io.StringIO())

    suppress = _suppress_stdout if quiet else contextlib.nullcontext

    edhrec_conn = ec.open_cache(cache)
    with suppress():
        data = ec.fetch_commander(edhrec_conn, name)
    if data is None:
        typer.echo(f"ERROR: could not fetch EDHREC data for {name!r}", err=True)
        edhrec_conn.close()
        raise typer.Exit(1)

    decks = ec.num_decks(data)
    recommended = ec.all_recommended_cards(data)[:top]
    all_names = [card.name for card in recommended]

    scryfall_conn = sc.open_cache(cache)

    # Batch fetch: fetch_cards_by_names handles cache checks internally
    # and only hits the network for missing cards, batched 75 at a time.
    # Note: fetch_cards_by_names already sleeps between batches internally
    # (BATCH_DELAY), respecting Scryfall's rate-limit guidelines.
    fetched_cards = sc.fetch_cards_by_names(scryfall_conn, all_names)

    found = len(fetched_cards)
    errors = [n for n in all_names if n not in fetched_cards]

    typer.echo(f"EDHREC: {name} - {decks} decks, evaluating top {len(recommended)}")
    typer.echo(f"Cache: {found} card(s) loaded, {len(errors)} not found.")
    for card_name in errors:
        typer.echo(f"  ! could not fetch: {card_name}")

    scryfall_conn.close()
    if edhrec_conn is not scryfall_conn:
        edhrec_conn.close()


# Verify


@app.command()
def verify(
    decklist: Annotated[str, typer.Option(help="Path to the decklist .txt file.")],
    collection: Annotated[str, typer.Option(help="Path to collection CSV path.")],
    cache: CachePath = DB_PATH,
) -> None:
    """Check which decklist cards are missing from the MTGA collection."""
    import sqlite3

    from manascope.collection import (
        BASIC_LANDS,
        RARITY_ORDER,
        load_collection_names,
        lookup_rarity,
    )
    from manascope.deck import parse_decklist

    entries = parse_decklist(decklist)
    owned = load_collection_names(Path(collection))

    cache_conn: sqlite3.Connection | None = None
    if Path(cache).exists():
        cache_conn = sqlite3.connect(str(cache))

    non_basic: list[str] = []
    missing_cards: list[str] = []

    for _, ident in entries:
        name = ident.name
        if name.lower() in BASIC_LANDS:
            continue
        non_basic.append(name)
        low = name.lower()
        # Normalize single-slash DFC separator to double-slash for matching
        normalized = low.replace(" / ", " // ")
        if normalized in owned:
            continue
        # Check front-face only (handles both "Front / Back" and "Front // Back")
        front = normalized.split(" // ", 1)[0] if " // " in normalized else low
        if front in owned:
            continue
        missing_cards.append(name)

    typer.echo(
        f"Checked {len(non_basic)} non-basic cards against collection ({len(owned)} unique owned)."
    )

    if not missing_cards:
        typer.echo("* All cards owned - deck is importable without crafting.")
        if cache_conn:
            cache_conn.close()
        return

    card_rarity: dict[str, str] = {}
    for card_name in missing_cards:
        card_rarity[card_name] = lookup_rarity(cache_conn, card_name) if cache_conn else "unknown"

    by_rarity: dict[str, list[str]] = {}
    for card_name, rarity in card_rarity.items():
        by_rarity.setdefault(rarity, []).append(card_name)

    typer.echo("")
    for rarity in RARITY_ORDER:
        cards = by_rarity.pop(rarity, [])
        if not cards:
            continue
        typer.echo(f"  [{rarity.upper()}]")
        for c in sorted(cards):
            typer.echo(f"    * {c}")
    for rarity, cards in sorted(by_rarity.items()):
        if not cards:
            continue
        typer.echo(f"  [{rarity.upper()}]")
        for c in sorted(cards):
            typer.echo(f"    * {c}")

    counts: dict[str, int] = {}
    for r in card_rarity.values():
        counts[r] = counts.get(r, 0) + 1
    parts = [f"{counts[r]} {r}" for r in RARITY_ORDER if r in counts]
    for r in sorted(counts):
        if r not in RARITY_ORDER:
            parts.append(f"{counts[r]} {r}")
    typer.echo(f"\n{len(missing_cards)} card(s) missing: {', '.join(parts)}")

    if cache_conn:
        cache_conn.close()
    raise typer.Exit(1)


# Lookup


@app.command()
def lookup(
    names: Annotated[list[str], typer.Argument(help="Card name(s) to look up.")],
    exact: Annotated[bool, typer.Option("--exact", help="Require exact name match.")] = False,
    brief: Annotated[bool, typer.Option("--brief", help="Omit rarity and price.")] = False,
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Cache-prime only; summary line.")
    ] = False,
    json_flag: Annotated[
        bool, typer.Option("--json", help="Machine-readable JSON output.")
    ] = False,
    refresh: Annotated[
        bool, typer.Option("--refresh", help="Force re-fetch from Scryfall.")
    ] = False,
    cache: CachePath = DB_PATH,
) -> None:
    """Look up cards by name (cache-first, fetches on miss)."""
    import json as json_mod

    from manascope import scryfall as sc
    from manascope.display import _card_to_json, _display_card

    conn = sc.open_cache(cache)
    cached_count = 0
    error_count = 0
    json_results: list[dict] = []

    for name in names:
        card = sc.fetch_card_by_name(conn, name, fuzzy=not exact, force_refresh=refresh)
        if card is None:
            typer.echo(f"ERROR: Card {name!r} not found.", err=True)
            error_count += 1
            continue
        cached_count += 1
        if json_flag:
            json_results.append(_card_to_json(card))
        elif not quiet:
            _display_card(card, brief=brief)

    if json_flag:
        print(json_mod.dumps(json_results))
    elif quiet:
        typer.echo(f"Cached {cached_count} card(s), {error_count} error(s).")

    conn.close()
    if error_count:
        raise typer.Exit(1)


# Edhrec


@app.command()
def edhrec(
    commander: Annotated[list[str], typer.Argument(help="Commander name or slug.")],
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Single summary line.")] = False,
    json_flag: Annotated[
        bool, typer.Option("--json", help="Machine-readable JSON output.")
    ] = False,
    cache: CachePath = DB_PATH,
) -> None:
    """Display EDHREC commander data (type dist, curve, synergy, combos, themes)."""
    from manascope import edhrec as ec

    commander_input = " ".join(commander)
    db = ec.open_cache(cache)

    if not quiet and not json_flag:
        typer.echo(f"\nLooking up via EDHREC: {commander_input}")
    result = ec.fetch_commander(db, commander_input)
    if result is None:
        typer.echo("Not found.", err=True)
        db.close()
        raise typer.Exit(1)

    if quiet:
        name = result.get("header", commander_input)
        typer.echo(f"EDHREC: {name} - {ec.num_decks(result):,} decks (cache primed)")
        db.close()
        return

    if json_flag:
        import json as json_mod

        td = ec.type_distribution(result)
        compact = {
            "name": result.get("header", commander_input),
            "num_decks": ec.num_decks(result),
            "type_distribution": td._asdict(),
            "mana_curve": ec.mana_curve(result),
            "high_synergy_cards": [
                {"name": c.name, "synergy": c.synergy_pct, "inclusion": c.inclusion_pct}
                for c in ec.high_synergy_cards(result)[:15]
            ],
            "combos": [c.description for c in ec.combos(result)] if ec.combos(result) else [],
            "themes": [{"name": t.name, "count": t.count} for t in ec.tags(result)[:10]]
            if ec.tags(result)
            else [],
        }
        print(json_mod.dumps(compact))
        db.close()
        return

    td = ec.type_distribution(result)
    pct = td.as_percentages()
    scaled_60 = td.scaled_to(60)
    mc = ec.mana_curve(result)
    hs = ec.high_synergy_cards(result)
    cb = ec.combos(result)
    tg = ec.tags(result)

    typer.echo(f"\n{'=' * 60}")
    typer.echo(f"  {result.get('header', '???')}")
    typer.echo(f"  {ec.num_decks(result):,} decks sampled")
    typer.echo(f"{'=' * 60}")

    typer.echo("\n  Average Type Distribution (100-card Commander):")
    typer.echo(f"  {'Type':<15} {'Count':>5}  {'%':>5}  {'→ 60-card':>9}")
    typer.echo(f"  {'-' * 40}")
    for field in ec.TypeDistribution._fields:
        if field == "total":
            continue
        count = getattr(td, field)
        if count == 0:
            continue
        typer.echo(
            f"  {field.capitalize():<15} {count:>5}  {pct[field]:>5.1f}%  {scaled_60[field]:>9}"
        )
    typer.echo(f"  {'-' * 40}")
    typer.echo(f"  {'Total':<15} {td.total:>5}  {'100.0':>5}%  {60:>9}")

    typer.echo("\n  Mana Curve:")
    for mv in sorted(mc.keys()):
        bar = "#" * mc[mv]
        typer.echo(f"    {mv}mv: {bar} ({mc[mv]})")

    typer.echo("\n  Top 10 High Synergy Cards:")
    for i, card in enumerate(hs[:10], 1):
        typer.echo(
            f"    {i:>2}. {card.name:<35} "
            f"syn={card.synergy_pct:>5.1f}%  "
            f"inc={card.inclusion_pct:>5.1f}%"
        )

    if cb:
        typer.echo("\n  Combos:")
        for combo in cb:
            typer.echo(f"    * {combo.description}")
        url = ec.combos_url(result)
        if url:
            typer.echo(f"    → {url}")

    if tg:
        typer.echo("\n  Top 10 Themes:")
        for tag in tg[:10]:
            typer.echo(f"    {tag.name:<20} ({tag.count} decks)")

    typer.echo("")
    db.close()
