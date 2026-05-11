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


def _print_notice(machine_readable: bool = False) -> None:
    """Print the unofficial fan project notice to stderr, only when stderr is a TTY
    and output is not machine-readable."""
    if machine_readable or not _notice_console.is_terminal:
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
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Fail (exit code 1) on any malformed decklist line."),
    ] = False,
    cache: CachePath = DB_PATH,
) -> None:
    """Full mana-base and deck analysis."""
    _print_notice(machine_readable=agent or json_flag)
    from manascope.analyze import run
    from manascope.deck import DecklistParseError

    try:
        run(
            decklist=decklist,
            cache=str(cache),
            fmt=fmt,
            compact=compact,
            agent=agent,
            json_flag=json_flag,
            strict=strict,
        )
    except DecklistParseError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(1) from exc


# Review


@app.command()
def review(
    decklist: Annotated[str, typer.Option(help="Path to the decklist .txt file.")],
    collection: Annotated[
        list[str] | None, typer.Option(help="Path(s) to collection CSV file(s).")
    ] = None,
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
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Fail (exit code 1) on any malformed decklist line."),
    ] = False,
    cache: CachePath = DB_PATH,
) -> None:
    """EDHREC cross-reference and owned-card gap analysis."""
    _print_notice(machine_readable=agent or json_flag)
    from manascope.deck import DecklistParseError
    from manascope.review import run

    try:
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
            strict=strict,
        )
    except DecklistParseError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(1) from exc


# Pipeline


@app.command()
def pipeline(
    decklist: Annotated[str, typer.Option(help="Path to the decklist .txt file.")],
    collection: Annotated[
        list[str] | None, typer.Option(help="Path(s) to collection CSV file(s).")
    ] = None,
    fmt: Annotated[
        str | None,
        typer.Option("--format", help="Override format (commander|brawl|standardbrawl)."),
    ] = None,
    top: Annotated[int, typer.Option(help="Number of EDHREC cards to evaluate.")] = 80,
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Fail (exit code 1) on any malformed decklist line."),
    ] = False,
    summary: Annotated[
        bool,
        typer.Option(
            "--summary",
            help="Emit a single status line instead of full JSON (fast triage).",
        ),
    ] = False,
    cache: CachePath = DB_PATH,
) -> None:
    """Run a combined JSON pipeline analysis for AI agents."""
    _print_notice(machine_readable=True)
    import json

    from manascope.analyze import run as run_analyze
    from manascope.deck import DecklistParseError
    from manascope.review import run as run_review

    try:
        analyze_data = run_analyze(
            decklist=decklist,
            cache=str(cache),
            fmt=fmt,
            return_data=True,
            json_flag=True,
            strict=strict,
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
            strict=strict,
        )
    except DecklistParseError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(1) from exc

    verify_data: dict | None = None
    if collection:
        # Re-run verification using the shared helper so the pipeline output
        # carries the same ownership data the standalone verify command would
        # — saves agents an extra command call after pipeline.
        from manascope import scryfall as sc
        from manascope.collection import (
            load_collection_names,
            load_collections_names,
        )
        from manascope.deck import parse_decklist
        from manascope.verify import verify_decklist

        try:
            entries = parse_decklist(decklist, strict=strict)
        except DecklistParseError as exc:
            typer.echo(f"ERROR: {exc}", err=True)
            raise typer.Exit(1) from exc

        paths = [Path(p) for p in collection]
        owned = load_collections_names(paths) if len(paths) > 1 else load_collection_names(paths[0])
        v_conn = sc.open_cache(Path(cache))
        try:
            verify_data = verify_decklist(entries, owned, v_conn)
        finally:
            v_conn.close()

    combined: dict = {
        "analyze": analyze_data,
        "review": review_data,
    }
    if verify_data is not None:
        combined["verify"] = verify_data

    if summary:
        print(_pipeline_summary_line(combined))
        return

    print(json.dumps(combined))


def _pipeline_summary_line(combined: dict) -> str:
    """Render the pipeline result as a single status line for fast triage.

    Format::

        <STATUS> <total>/<expected> lands=<n> <C>=<src>(<bal>) ... \
            gaps_owned=<n> gaps_unowned=<n> [missing=<n>]

    ``STATUS`` is ``OK`` when card count matches the format target and (when a
    collection is provided) no cards are missing; otherwise ``FAIL``. Balance
    statuses come straight from ``analyze.balance[colour].status``.
    """
    az = combined.get("analyze") or {}
    rv = combined.get("review") or {}
    vf = combined.get("verify")

    cards = az.get("cards") or {}
    total = cards.get("total")
    expected = cards.get("expected")
    cards_ok = cards.get("ok", True)
    lands = cards.get("lands")

    parts: list[str] = []
    if total is not None and expected is not None:
        parts.append(f"{total}/{expected}")
    elif total is not None:
        parts.append(str(total))
    if lands is not None:
        parts.append(f"lands={lands}")

    balance = az.get("balance") or {}
    for colour, info in balance.items():
        src = info.get("source_count", "?")
        bal = info.get("status", "?")
        parts.append(f"{colour}={src}({bal})")

    stats = rv.get("stats") or {}
    if "gaps_owned" in stats:
        parts.append(f"gaps_owned={stats['gaps_owned']}")
    if "gaps_not_owned" in stats:
        parts.append(f"gaps_unowned={stats['gaps_not_owned']}")

    missing = None
    if isinstance(vf, dict):
        missing = vf.get("missing_count")
        parts.append(f"missing={missing}")

    balance_ok = (
        all((info or {}).get("status") == "OK" for info in balance.values()) if balance else True
    )
    status = "OK" if cards_ok and balance_ok and (missing in (None, 0)) else "FAIL"
    return status + " " + " ".join(parts)


# Prime


@app.command()
def prime(
    name: Annotated[str, typer.Argument(help="Commander name (display name or slug).")],
    top: Annotated[int, typer.Option(help="Number of EDHREC cards to evaluate.")] = 80,
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Suppress per-card messages.")
    ] = False,
    json_flag: Annotated[
        bool,
        typer.Option(
            "--json",
            help=(
                "Emit a structured JSON report of primed cards (commander, deck "
                "sample, primed list, missing list). Implies --quiet."
            ),
        ),
    ] = False,
    cache: CachePath = DB_PATH,
) -> None:
    """Prime the Scryfall cache with EDHREC-recommended cards."""
    # JSON output must be the only thing on stdout for agents to parse it; force
    # quiet so suppression covers the EDHREC fetch chatter as well.
    if json_flag:
        quiet = True
    _print_notice(machine_readable=quiet)
    import json as json_mod

    from manascope import edhrec as ec
    from manascope import scryfall as sc

    def _suppress_stdout():
        return contextlib.redirect_stdout(io.StringIO())

    suppress = _suppress_stdout if quiet else contextlib.nullcontext

    # Both modules share the same on-disk cache; open it once. Calling
    # ec.open_cache once up-front guarantees the edhrec_commanders table
    # exists before we write to it via ec.fetch_commander.
    ec.open_cache(cache).close()
    conn = sc.open_cache(cache)
    try:
        with suppress():
            data = ec.fetch_commander(conn, name)
        if data is None:
            if json_flag:
                print(
                    json_mod.dumps(
                        {
                            "commander": name,
                            "error": "could not fetch EDHREC data",
                            "decks": 0,
                            "evaluated": 0,
                            "cached": 0,
                            "missing_count": 0,
                            "primed": [],
                            "missing": [],
                        }
                    )
                )
            else:
                typer.echo(f"ERROR: could not fetch EDHREC data for {name!r}", err=True)
            conn.close()
            raise typer.Exit(1)

        decks = ec.num_decks(data)
        recommended = ec.all_recommended_cards(data)[:top]
        all_names = [card.name for card in recommended]

        # Batch fetch: fetch_cards_by_names handles cache checks internally
        # and only hits the network for missing cards, batched 75 at a time.
        # Note: fetch_cards_by_names already sleeps between batches internally
        # (BATCH_DELAY), respecting Scryfall's rate-limit guidelines.
        fetched_cards = sc.fetch_cards_by_names(conn, all_names)

        found = len(fetched_cards)
        errors = [n for n in all_names if n not in fetched_cards]

        if json_flag:
            # Resolve canonical Scryfall names so primed[] matches what
            # downstream commands (lookup/edhrec) will use as keys.
            primed: list[dict] = []
            for requested in all_names:
                cj = fetched_cards.get(requested)
                if cj is None:
                    continue
                primed.append(
                    {
                        "name": cj.get("name", requested),
                        "requested": requested,
                        "set": (cj.get("set") or "").upper() or None,
                        "collector_number": cj.get("collector_number"),
                        "rarity": cj.get("rarity"),
                    }
                )
            print(
                json_mod.dumps(
                    {
                        "commander": ec.commander_display_name(data, fallback=name),
                        "decks": decks,
                        "evaluated": len(recommended),
                        "cached": found,
                        "missing_count": len(errors),
                        "primed": primed,
                        "missing": errors,
                    }
                )
            )
            return

        typer.echo(f"EDHREC: {name} - {decks} decks, evaluating top {len(recommended)}")
        typer.echo(f"Cache: {found} card(s) loaded, {len(errors)} not found.")
        for card_name in errors:
            typer.echo(f"  ! could not fetch: {card_name}")
    finally:
        conn.close()


# Verify


@app.command()
def verify(
    decklist: Annotated[str, typer.Option(help="Path to the decklist .txt file.")],
    collection: Annotated[list[str], typer.Option(help="Path(s) to collection CSV file(s).")],
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Fail (exit code 1) on any malformed decklist line."),
    ] = False,
    json_flag: Annotated[
        bool, typer.Option("--json", help="Machine-readable JSON output.")
    ] = False,
    fix: Annotated[
        bool,
        typer.Option(
            "--fix",
            help=(
                "Rewrite the decklist with corrected (SET) CN for any line whose "
                "printing isn't in the cache, using a known printing of the same "
                "card. Only safe printings (cached) are substituted; missing "
                "cards are left untouched and still reported."
            ),
        ),
    ] = False,
    printings: Annotated[
        bool,
        typer.Option(
            "--printings",
            help=(
                "Also verify each line's exact (SET) CN matches a non-foil printing "
                "in the collection CSV. Adds 'wrong_printing' to the JSON output for "
                "any decklist line whose card name is owned but at a different "
                "printing. Requires a ManaBox-style CSV with Set code, Collector "
                "number, and Foil columns; silently inactive for MTGA exports."
            ),
        ),
    ] = False,
    cache: CachePath = DB_PATH,
) -> None:
    """Check which decklist cards are missing from the MTGA collection."""
    _print_notice(machine_readable=json_flag)
    import json as json_mod
    import sqlite3

    from manascope import scryfall as sc
    from manascope.collection import (
        RARITY_ORDER,
        load_collection_names,
        load_collection_printings,
        load_collections_names,
        load_collections_printings,
    )
    from manascope.deck import DecklistParseError, parse_decklist
    from manascope.verify import verify_decklist

    try:
        entries = parse_decklist(decklist, strict=strict)
    except DecklistParseError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(1) from exc

    owned = (
        load_collections_names([Path(p) for p in collection])
        if len(collection) > 1
        else load_collection_names(Path(collection[0]))
    )
    owned_printings = None
    if printings:
        owned_printings = (
            load_collections_printings([Path(p) for p in collection])
            if len(collection) > 1
            else load_collection_printings(Path(collection[0]))
        )

    # Always go through sc.open_cache so the schema is idempotently ensured
    # even if an empty or stray cache.db file happens to exist.
    cache_conn: sqlite3.Connection | None = sc.open_cache(Path(cache))

    fix_report: dict | None = None
    if fix:
        fix_report = _fix_decklist_printings(Path(decklist), entries, cache_conn)
        # Re-parse so missing-card reporting reflects the rewritten file.
        entries = parse_decklist(decklist, strict=strict)

    result = verify_decklist(entries, owned, cache_conn, owned_printings=owned_printings)

    if json_flag:
        payload: dict = {
            "checked": result["checked"],
            "owned_count": result["owned_count"],
            "missing_count": result["missing_count"],
            "missing": result["missing"],
            "by_rarity": {r: names for r, names in result["by_rarity"].items()},
        }
        if "wrong_printing" in result:
            payload["wrong_printing_count"] = result["wrong_printing_count"]
            payload["wrong_printing"] = result["wrong_printing"]
        if fix_report is not None:
            payload["fix"] = fix_report
        print(json_mod.dumps(payload))
        if cache_conn:
            cache_conn.close()
        if result["missing_count"] or result.get("wrong_printing_count", 0):
            raise typer.Exit(1)
        return

    typer.echo(
        f"Checked {result['checked']} non-basic cards against collection "
        f"({result['owned_count']} unique owned)."
    )
    if fix_report is not None:
        typer.echo(
            f"Fix: rewrote {fix_report['rewritten']} line(s); "
            f"{fix_report['unresolved']} unresolved."
        )

    if result["missing_count"] == 0 and not result.get("wrong_printing_count"):
        typer.echo("* All cards owned - deck is importable without crafting.")
        if cache_conn:
            cache_conn.close()
        return

    if result.get("wrong_printing_count"):
        typer.echo("")
        typer.echo(f"  [WRONG PRINTING] ({result['wrong_printing_count']})")
        for wp in result["wrong_printing"]:
            typer.echo(f"    * {wp['name']} ({wp['set']}) {wp['collector_number']}")

    typer.echo("")
    for rarity, cards in result["by_rarity"].items():
        if not cards:
            continue
        typer.echo(f"  [{rarity.upper()}]")
        for c in cards:
            typer.echo(f"    * {c}")

    counts: dict[str, int] = {r: len(names) for r, names in result["by_rarity"].items()}
    parts = [f"{counts[r]} {r}" for r in RARITY_ORDER if r in counts]
    for r in sorted(counts):
        if r not in RARITY_ORDER:
            parts.append(f"{counts[r]} {r}")
    typer.echo(f"\n{result['missing_count']} card(s) missing: {', '.join(parts)}")

    if cache_conn:
        cache_conn.close()
    raise typer.Exit(1)


def _fix_decklist_printings(
    path: Path,
    entries: object,
    cache_conn,
) -> dict:
    """Rewrite a decklist file in-place, replacing bad ``(SET) CN`` with cached printings.

    A line is considered "bad" when its (set, collector_number) tuple isn't
    in the Scryfall cache but the card's *name* is. The replacement uses
    whatever printing :func:`scryfall.get_card_by_name` returns, which is
    the most recently fetched one — stable enough for re-import since
    Arena matches on name + set anyway.

    Returns a report dict with ``rewritten``, ``unresolved``, and
    ``replacements`` (a list of ``{old, new}`` strings).
    """
    from manascope import scryfall as sc

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    replacements: list[dict[str, str]] = []
    unresolved: list[str] = []

    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.lower() in {"commander", "deck", "sideboard", "companion"}:
            new_lines.append(line)
            continue
        from manascope.deck import LINE_RE

        m = LINE_RE.match(stripped)
        if not m:
            new_lines.append(line)
            continue
        qty = m.group("qty")
        name = m.group("name")
        set_code = m.group("set")
        cn = m.group("number")

        # Already cached at this printing? Leave it.
        if sc.get_card_by_id(cache_conn, set_code, cn) is not None:
            new_lines.append(line)
            continue

        # Try to find any cached printing of this card by name.
        card = sc.get_card_by_name(cache_conn, name)
        if card is None:
            unresolved.append(name)
            new_lines.append(line)
            continue

        new_set = card.get("set", set_code).upper()
        new_cn = card.get("collector_number", cn)
        new_line = f"{qty} {name} ({new_set}) {new_cn}"
        replacements.append({"old": stripped, "new": new_line})
        new_lines.append(new_line)

    if replacements:
        path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    # Suppress unused-arg warning when entries isn't needed (we re-parse).
    _ = entries

    return {
        "rewritten": len(replacements),
        "unresolved": len(unresolved),
        "replacements": replacements,
        "unresolved_names": sorted(set(unresolved)),
    }


# Lookup


@app.command()
def lookup(
    names: Annotated[list[str], typer.Argument(help="Card name(s) to look up.")],
    exact: Annotated[bool, typer.Option("--exact", help="Require exact name match.")] = False,
    brief: Annotated[bool, typer.Option("--brief", help="Omit rarity and price.")] = False,
    minimal: Annotated[
        bool,
        typer.Option(
            "--minimal",
            help=(
                "JSON only: drop oracle_text, colors, rarity, P/T/loyalty, "
                "notable_types, land_equiv, and produced_mana for ~60-80% "
                "smaller payloads. Implies --json."
            ),
        ),
    ] = False,
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
    # --minimal is a JSON-only knob; auto-imply --json so agents don't have to
    # remember to pass both flags together.
    if minimal:
        json_flag = True
    _print_notice(machine_readable=json_flag or quiet)
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
            json_results.append(_card_to_json(card, conn=conn, minimal=minimal))
        elif not quiet:
            _display_card(card, brief=brief)

    if json_flag:
        print(json_mod.dumps(json_results))
    elif quiet:
        typer.echo(f"Cached {cached_count} card(s), {error_count} error(s).")

    conn.close()
    if error_count:
        raise typer.Exit(1)


# Collection


@app.command()
def collection(
    collection: Annotated[
        list[str], typer.Option("--collection", help="Path(s) to collection CSV/JSON file(s).")
    ],
    color: Annotated[
        str | None,
        typer.Option(
            "--color",
            help="Exact color identity match (e.g. 'BW', 'R', '' for colourless).",
        ),
    ] = None,
    in_identity: Annotated[
        str | None,
        typer.Option(
            "--in-identity",
            help="Subset match (cards castable in this identity, e.g. 'BW' includes B, W, colourless).",
        ),
    ] = None,
    type_substr: Annotated[
        str | None,
        typer.Option("--type", help="Substring match against type_line (case-insensitive)."),
    ] = None,
    rarity: Annotated[
        str | None,
        typer.Option("--rarity", help="common|uncommon|rare|mythic|special."),
    ] = None,
    cmc: Annotated[int | None, typer.Option("--cmc", help="Exact CMC.")] = None,
    cmc_max: Annotated[
        int | None, typer.Option("--cmc-max", help="Maximum CMC (inclusive).")
    ] = None,
    legal: Annotated[
        str | None,
        typer.Option("--legal", help="Filter to cards legal in commander|brawl|standardbrawl."),
    ] = None,
    json_flag: Annotated[
        bool, typer.Option("--json", help="Machine-readable JSON output.")
    ] = False,
    cache: CachePath = DB_PATH,
) -> None:
    """Filter the collection by color/type/rarity/CMC/legality.

    Cards not present in the Scryfall cache are skipped; prime them via
    ``manascope lookup`` or ``manascope prime`` first if you need them.
    """
    _print_notice(machine_readable=json_flag)
    import json as json_mod

    from manascope import scryfall as sc
    from manascope.collection import (
        filter_collection,
        load_collection,
        load_collections,
    )

    paths = [Path(p) for p in collection]
    owned = load_collections(paths) if len(paths) > 1 else load_collection(paths[0])

    conn = sc.open_cache(cache)
    try:
        results = filter_collection(
            owned,
            conn,
            color_identity=color,
            within_identity=in_identity,
            type_substr=type_substr,
            rarity=rarity,
            cmc=cmc,
            cmc_max=cmc_max,
            legal_in=legal,
        )
    finally:
        conn.close()

    if json_flag:
        print(json_mod.dumps(results))
        return

    if not results:
        typer.echo("No cards match the given filters.")
        return

    typer.echo(f"{len(results)} card(s) match:")
    for r in results:
        ci = "".join(r["color_identity"]) or "C"
        typer.echo(
            f"  {r['count']:>2}x  {r['rarity'][:1].upper()}  CI={ci:<5}  "
            f"cmc{int(r['cmc']):>2}  {r['type_line'][:38]:38}  {r['name']}"
        )


# Build


@app.command()
def build(
    commander: Annotated[list[str], typer.Argument(help="Commander name (or slug).")],
    collection: Annotated[
        list[str], typer.Option("--collection", help="Path(s) to collection CSV/JSON file(s).")
    ],
    fmt: Annotated[
        str,
        typer.Option("--format", help="Format: commander|brawl|standardbrawl. Default brawl."),
    ] = "brawl",
    top: Annotated[int, typer.Option("--top", help="Number of EDHREC cards to evaluate.")] = 80,
    lands: Annotated[
        int | None,
        typer.Option("--lands", help="Land count. Default 35 for 100-card, 22 for 60-card."),
    ] = None,
    output: Annotated[
        str | None,
        typer.Option("--output", "-o", help="Write decklist to this path instead of stdout."),
    ] = None,
    json_flag: Annotated[
        bool, typer.Option("--json", help="Emit a JSON build report instead of decklist text.")
    ] = False,
    cache: CachePath = DB_PATH,
) -> None:
    """Draft a deck from a commander + collection using EDHREC recommendations.

    Prerequisites: run ``manascope prime "<Commander>"`` first so that
    EDHREC data and the recommended cards' Scryfall entries are cached.
    The build command never hits the network.
    """
    _print_notice(machine_readable=json_flag)
    from manascope.build import run as build_run

    commander_name = " ".join(commander)
    paths = [Path(p) for p in collection]
    try:
        build_run(
            commander_name=commander_name,
            collection_paths=paths,
            fmt=fmt,
            top=top,
            lands=lands,
            output=Path(output) if output else None,
            json_flag=json_flag,
            cache=Path(cache),
        )
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(1) from exc


# Edhrec


@app.command()
def edhrec(
    commander: Annotated[list[str], typer.Argument(help="Commander name or slug.")],
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Single summary line.")] = False,
    json_flag: Annotated[
        bool, typer.Option("--json", help="Machine-readable JSON output.")
    ] = False,
    top: Annotated[
        int,
        typer.Option(
            "--top",
            help="Number of recommended cards to emit in --json mode (sorted by synergy).",
        ),
    ] = 80,
    cache: CachePath = DB_PATH,
) -> None:
    """Display EDHREC commander data (type dist, curve, synergy, combos, themes)."""
    _print_notice(machine_readable=json_flag or quiet)
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
        name = ec.commander_display_name(result, fallback=commander_input)
        typer.echo(f"EDHREC: {name} - {ec.num_decks(result):,} decks (cache primed)")
        db.close()
        return

    if json_flag:
        import json as json_mod

        td = ec.type_distribution(result)
        compact = {
            "name": ec.commander_display_name(result, fallback=commander_input),
            "num_decks": ec.num_decks(result),
            "type_distribution": td._asdict(),
            "mana_curve": ec.mana_curve(result),
            "high_synergy_cards": [
                {"name": c.name, "synergy": c.synergy_pct, "inclusion": c.inclusion_pct}
                for c in ec.high_synergy_cards(result)[:15]
            ],
            "recommended": [
                {
                    "name": c.name,
                    "synergy": c.synergy_pct,
                    "inclusion": c.inclusion_pct,
                    "category": c.category,
                }
                for c in ec.all_recommended_cards(result)[:top]
            ],
            "combos": [c.description for c in ec.combos(result)] if ec.combos(result) else [],
            "themes": [{"name": t.name, "count": t.deck_count} for t in ec.tags(result)[:10]]
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
            typer.echo(f"    {tag.name:<20} ({tag.deck_count} decks)")

    typer.echo("")
    db.close()
