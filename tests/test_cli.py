import json
from pathlib import Path

import pytest_mock
from typer.testing import CliRunner

from manascope.cli import app

runner = CliRunner()


def test_pipeline_command(mocker: pytest_mock.MockerFixture, tmp_path: Path) -> None:
    mock_run_analyze = mocker.patch("manascope.analyze.run")
    mock_run_review = mocker.patch("manascope.review.run")

    # Setup mock returns
    mock_run_analyze.return_value = {"mana": {"raw": 100}}
    mock_run_review.return_value = {"stats": {"in_deck": 10}}

    # Create a dummy decklist
    decklist_file = tmp_path / "dummy.txt"
    decklist_file.write_text("1 Commander\n")

    # Run the command
    result = runner.invoke(app, ["pipeline", "--decklist", str(decklist_file)])

    assert result.exit_code == 0

    # Parse the output
    output_data = json.loads(result.stdout)
    assert "analyze" in output_data
    assert "review" in output_data
    assert output_data["analyze"]["mana"]["raw"] == 100
    assert output_data["review"]["stats"]["in_deck"] == 10
    # No collection → no verify section.
    assert "verify" not in output_data


def test_pipeline_includes_verify_when_collection_provided(
    mocker: pytest_mock.MockerFixture, tmp_path: Path
) -> None:
    """Adding --collection should fold a verify_decklist call into the JSON output.

    Saves agents from running pipeline + verify back-to-back.
    """
    mocker.patch("manascope.analyze.run", return_value={"ok": True})
    mocker.patch("manascope.review.run", return_value={"stats": {}})
    mocker.patch(
        "manascope.verify.verify_decklist",
        return_value={
            "checked": 99,
            "owned_count": 4242,
            "missing_count": 2,
            "missing": [{"name": "X", "rarity": "rare"}],
            "by_rarity": {"rare": ["X"]},
        },
    )
    mocker.patch("manascope.scryfall.open_cache")

    decklist = tmp_path / "d.txt"
    decklist.write_text("1 X (NEO) 1\n")
    csv = tmp_path / "c.csv"
    csv.write_text(
        "Count,Name,Edition,Condition,Language,Foil,Tag\n1,X,NEO,Near Mint,English,,\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["pipeline", "--decklist", str(decklist), "--collection", str(csv)],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["verify"]["missing_count"] == 2
    assert payload["verify"]["by_rarity"] == {"rare": ["X"]}


def test_pipeline_summary_emits_ok_status_line(
    mocker: pytest_mock.MockerFixture, tmp_path: Path
) -> None:
    """--summary collapses analyze + review into a single greppable status line."""
    mocker.patch(
        "manascope.analyze.run",
        return_value={
            "format": "brawl",
            "cards": {"total": 100, "expected": 100, "ok": True, "lands": 35, "spells": 64},
            "balance": {
                "W": {"source_count": 14, "pip_pct": 45.0, "status": "OK"},
                "B": {"source_count": 15, "pip_pct": 55.0, "status": "OK"},
            },
        },
    )
    mocker.patch(
        "manascope.review.run",
        return_value={"stats": {"sample": 1, "in_deck": 60, "gaps_owned": 2, "gaps_not_owned": 8}},
    )

    decklist = tmp_path / "d.txt"
    decklist.write_text("1 X (NEO) 1\n")

    result = runner.invoke(app, ["pipeline", "--decklist", str(decklist), "--summary"])
    assert result.exit_code == 0, result.stdout
    line = result.stdout.strip().splitlines()[-1]
    assert line.startswith("OK ")
    assert "100/100" in line
    assert "lands=35" in line
    assert "W=14(OK)" in line
    assert "B=15(OK)" in line
    assert "gaps_owned=2" in line
    assert "gaps_unowned=8" in line
    # Without --collection there is no verify block, so no missing= field.
    assert "missing=" not in line
    # --summary must not also dump the full JSON payload.
    assert '"analyze"' not in result.stdout


def test_pipeline_summary_marks_fail_on_card_count_mismatch(
    mocker: pytest_mock.MockerFixture, tmp_path: Path
) -> None:
    mocker.patch(
        "manascope.analyze.run",
        return_value={
            "cards": {"total": 99, "expected": 100, "ok": False, "lands": 34, "spells": 64},
            "balance": {
                "W": {"source_count": 14, "pip_pct": 45.0, "status": "OK"},
                "B": {"source_count": 15, "pip_pct": 55.0, "status": "OK"},
            },
        },
    )
    mocker.patch(
        "manascope.review.run",
        return_value={"stats": {"gaps_owned": 0, "gaps_not_owned": 0}},
    )

    decklist = tmp_path / "d.txt"
    decklist.write_text("1 X (NEO) 1\n")

    result = runner.invoke(app, ["pipeline", "--decklist", str(decklist), "--summary"])
    assert result.exit_code == 0, result.stdout
    line = result.stdout.strip().splitlines()[-1]
    assert line.startswith("FAIL ")
    assert "99/100" in line


def test_pipeline_summary_marks_fail_on_balance_problem(
    mocker: pytest_mock.MockerFixture, tmp_path: Path
) -> None:
    mocker.patch(
        "manascope.analyze.run",
        return_value={
            "cards": {"total": 100, "expected": 100, "ok": True, "lands": 35, "spells": 64},
            "balance": {
                "W": {"source_count": 6, "pip_pct": 50.0, "status": "UNDER"},
                "B": {"source_count": 15, "pip_pct": 50.0, "status": "OK"},
            },
        },
    )
    mocker.patch("manascope.review.run", return_value={"stats": {}})

    decklist = tmp_path / "d.txt"
    decklist.write_text("1 X (NEO) 1\n")

    result = runner.invoke(app, ["pipeline", "--decklist", str(decklist), "--summary"])
    assert result.exit_code == 0, result.stdout
    line = result.stdout.strip().splitlines()[-1]
    assert line.startswith("FAIL ")
    assert "W=6(UNDER)" in line


def test_pipeline_summary_includes_missing_when_collection_provided(
    mocker: pytest_mock.MockerFixture, tmp_path: Path
) -> None:
    mocker.patch(
        "manascope.analyze.run",
        return_value={
            "cards": {"total": 100, "expected": 100, "ok": True, "lands": 35, "spells": 64},
            "balance": {},
        },
    )
    mocker.patch("manascope.review.run", return_value={"stats": {}})
    mocker.patch(
        "manascope.verify.verify_decklist",
        return_value={
            "checked": 99,
            "owned_count": 4242,
            "missing_count": 3,
            "missing": [],
            "by_rarity": {},
        },
    )
    mocker.patch("manascope.scryfall.open_cache")

    decklist = tmp_path / "d.txt"
    decklist.write_text("1 X (NEO) 1\n")
    csv = tmp_path / "c.csv"
    csv.write_text(
        "Count,Name,Edition,Condition,Language,Foil,Tag\n1,X,NEO,Near Mint,English,,\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["pipeline", "--decklist", str(decklist), "--collection", str(csv), "--summary"],
    )
    assert result.exit_code == 0, result.stdout
    line = result.stdout.strip().splitlines()[-1]
    # Missing>0 forces FAIL even when card count and balance look fine.
    assert line.startswith("FAIL ")
    assert "missing=3" in line


def test_analyze_json_includes_card_count_block(
    mocker: pytest_mock.MockerFixture, tmp_path: Path
) -> None:
    """analyze --json must surface total_cards / expected for the format.

    Catches the silent off-by-one I shipped earlier this session (99 vs 100).
    """
    # Patch _compute_stats to return a stub DeckStats with known counts.
    from collections import Counter

    from manascope.analyze import DeckStats

    stub = DeckStats(
        commander_name="X",
        decklist=str(tmp_path / "d.txt"),
        deck_format="brawl",
        cache_path="",
        card_count=99,  # one short on purpose
        sorted_colours=[],
        colour_identity=set(),
        synergy_types=set(),
        commander_cmc=0,
        lands=[],
        spells=[],
        total_lands=34,
        total_spells=64,
        type_distribution=Counter(),
        source_count=Counter(),
        speed_counts=Counter({"untapped": 0, "shock": 0, "conditional": 0, "tapped": 0}),
        pip_counts=Counter(),
        needs_colour=Counter(),
        total_pips=0,
        rocks=[],
        mana_creatures=[],
        rock_total=0.0,
        effective_land_count=34.0,
        synergy_targets=[],
        non_synergy_creatures=[],
        cmc_counter=Counter(),
        balance_data={},
        eff_low=33.0,
        eff_high=36.0,
        land_target_label="33-35 raw",
        card_map_size=0,
    )
    mocker.patch("manascope.analyze._compute_stats", return_value=stub)

    decklist = tmp_path / "d.txt"
    decklist.write_text("1 X (NEO) 1\n")
    result = runner.invoke(app, ["analyze", "--decklist", str(decklist), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["format"] == "brawl"
    assert payload["cards"]["total"] == 99
    assert payload["cards"]["expected"] == 100
    assert payload["cards"]["ok"] is False
    assert payload["cards"]["lands"] == 34


def test_analyze_json_flag(mocker: pytest_mock.MockerFixture, tmp_path: Path) -> None:
    mock_run_analyze = mocker.patch("manascope.analyze.run")
    decklist_file = tmp_path / "dummy.txt"
    decklist_file.write_text("1 Commander\n")

    result = runner.invoke(app, ["analyze", "--decklist", str(decklist_file), "--json"])
    assert result.exit_code == 0
    mock_run_analyze.assert_called_once()
    assert mock_run_analyze.call_args[1]["json_flag"] is True


def test_review_json_flag(mocker: pytest_mock.MockerFixture, tmp_path: Path) -> None:
    mock_run_review = mocker.patch("manascope.review.run")
    decklist_file = tmp_path / "dummy.txt"
    decklist_file.write_text("1 Commander\n")

    result = runner.invoke(app, ["review", "--decklist", str(decklist_file), "--json"])
    assert result.exit_code == 0
    mock_run_review.assert_called_once()
    assert mock_run_review.call_args[1]["json_flag"] is True


def test_edhrec_json_flag(mocker: pytest_mock.MockerFixture) -> None:
    mocker.patch("manascope.edhrec.open_cache")
    mocker.patch(
        "manascope.edhrec.fetch_commander",
        return_value={"header": "Test Commander (Commander)"},
    )
    mocker.patch("manascope.edhrec.num_decks", return_value=100)

    mock_td = mocker.Mock()
    mock_td._asdict.return_value = {"Creature": 10}
    mocker.patch("manascope.edhrec.type_distribution", return_value=mock_td)
    mocker.patch("manascope.edhrec.mana_curve", return_value={"1": 5})
    mocker.patch("manascope.edhrec.high_synergy_cards", return_value=[])
    mocker.patch("manascope.edhrec.combos", return_value=[])
    mocker.patch("manascope.edhrec.tags", return_value=[])

    result = runner.invoke(app, ["edhrec", "Test", "Commander", "--json"])
    assert result.exit_code == 0
    output_data = json.loads(result.stdout)
    # Suffix must be stripped from the canonical name.
    assert output_data["name"] == "Test Commander"
    assert output_data["num_decks"] == 100


def test_edhrec_json_emits_full_recommended_list(mocker: pytest_mock.MockerFixture) -> None:
    """--top N should expose all top-N recommendations (not just top-10 high-synergy).

    Regression for the agent workflow gap that forced bootstrapping a stub deck
    just to read the top-80 list out of `pipeline.review.gaps_owned`.
    """
    from manascope.edhrec import SynergyCard

    mocker.patch("manascope.edhrec.open_cache")
    mocker.patch("manascope.edhrec.fetch_commander", return_value={"header": "X"})
    mocker.patch("manascope.edhrec.num_decks", return_value=1)
    td = mocker.Mock()
    td._asdict.return_value = {}
    mocker.patch("manascope.edhrec.type_distribution", return_value=td)
    mocker.patch("manascope.edhrec.mana_curve", return_value={})
    mocker.patch("manascope.edhrec.high_synergy_cards", return_value=[])
    mocker.patch("manascope.edhrec.combos", return_value=[])
    mocker.patch("manascope.edhrec.tags", return_value=[])

    fake_cards = [
        SynergyCard(name=f"Card {i}", synergy=0.5, inclusion=10, potential_decks=100, category="x")
        for i in range(50)
    ]
    mocker.patch("manascope.edhrec.all_recommended_cards", return_value=fake_cards)

    result = runner.invoke(app, ["edhrec", "X", "--json", "--top", "30"])
    assert result.exit_code == 0, result.stdout
    output = json.loads(result.stdout)
    assert "recommended" in output
    assert len(output["recommended"]) == 30
    assert output["recommended"][0]["name"] == "Card 0"
    # Each entry carries name, synergy, inclusion, category for downstream filtering.
    assert {"name", "synergy", "inclusion", "category"} <= output["recommended"][0].keys()


def test_lookup_minimal_implies_json_and_passes_minimal_flag(
    mocker: pytest_mock.MockerFixture, tmp_path: Path
) -> None:
    """--minimal must auto-imply --json and reach _card_to_json with minimal=True."""
    mocker.patch(
        "manascope.scryfall.fetch_card_by_name",
        return_value={"name": "X", "set": "neo", "collector_number": "1"},
    )
    mocker.patch("manascope.scryfall.open_cache")
    to_json = mocker.patch(
        "manascope.display._card_to_json",
        return_value={"name": "X"},
    )

    result = runner.invoke(app, ["lookup", "X", "--minimal"])
    assert result.exit_code == 0, result.stdout
    # --minimal implies --json: stdout must be parseable JSON.
    payload = json.loads(result.stdout)
    assert payload == [{"name": "X"}]
    # And the minimal flag must propagate into _card_to_json.
    assert to_json.call_args.kwargs.get("minimal") is True


def test_lookup_default_does_not_pass_minimal(
    mocker: pytest_mock.MockerFixture, tmp_path: Path
) -> None:
    """--json without --minimal must keep the full payload (regression guard)."""
    mocker.patch(
        "manascope.scryfall.fetch_card_by_name",
        return_value={"name": "X", "set": "neo", "collector_number": "1"},
    )
    mocker.patch("manascope.scryfall.open_cache")
    to_json = mocker.patch(
        "manascope.display._card_to_json",
        return_value={"name": "X"},
    )

    result = runner.invoke(app, ["lookup", "X", "--json"])
    assert result.exit_code == 0, result.stdout
    assert to_json.call_args.kwargs.get("minimal") is False


# ---- prime --json ----


def test_prime_json_emits_primed_card_report(mocker: pytest_mock.MockerFixture) -> None:
    """prime --json must emit a structured report of every primed card.

    Closes the gap where agents had to follow `prime` with `lookup` just to
    confirm what landed in cache.
    """
    from manascope.edhrec import SynergyCard

    mocker.patch("manascope.edhrec.open_cache")
    mocker.patch(
        "manascope.edhrec.fetch_commander",
        return_value={"header": "Greasefang, Okiba Boss (Commander)"},
    )
    mocker.patch("manascope.edhrec.num_decks", return_value=1234)
    mocker.patch(
        "manascope.edhrec.all_recommended_cards",
        return_value=[
            SynergyCard(
                name="Parhelion II",
                synergy=0.9,
                inclusion=80,
                potential_decks=100,
                category="top",
            ),
            SynergyCard(
                name="Bone Shards",
                synergy=0.7,
                inclusion=60,
                potential_decks=100,
                category="top",
            ),
            SynergyCard(
                name="Vanished Card",
                synergy=0.6,
                inclusion=40,
                potential_decks=100,
                category="top",
            ),
        ],
    )
    mocker.patch("manascope.scryfall.open_cache")
    mocker.patch(
        "manascope.scryfall.fetch_cards_by_names",
        return_value={
            "Parhelion II": {
                "name": "Parhelion II",
                "set": "snc",
                "collector_number": "246",
                "rarity": "mythic",
            },
            "Bone Shards": {
                "name": "Bone Shards",
                "set": "khm",
                "collector_number": "95",
                "rarity": "common",
            },
            # Vanished Card intentionally omitted
        },
    )

    result = runner.invoke(app, ["prime", "Greasefang", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    # commander must be the canonical card name without EDHREC's " (Commander)" suffix.
    assert payload["commander"] == "Greasefang, Okiba Boss"
    assert payload["decks"] == 1234
    assert payload["evaluated"] == 3
    assert payload["cached"] == 2
    assert payload["missing_count"] == 1
    assert payload["missing"] == ["Vanished Card"]
    primed_names = [p["name"] for p in payload["primed"]]
    assert primed_names == ["Parhelion II", "Bone Shards"]
    parhelion = payload["primed"][0]
    assert parhelion["set"] == "SNC"
    assert parhelion["collector_number"] == "246"
    assert parhelion["rarity"] == "mythic"


def test_prime_json_handles_missing_edhrec_data(mocker: pytest_mock.MockerFixture) -> None:
    """When EDHREC has nothing for the commander, --json must still emit valid JSON."""
    mocker.patch("manascope.edhrec.open_cache")
    mocker.patch("manascope.edhrec.fetch_commander", return_value=None)
    mocker.patch("manascope.scryfall.open_cache")

    result = runner.invoke(app, ["prime", "Nobody", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["commander"] == "Nobody"
    assert payload["error"] == "could not fetch EDHREC data"
    assert payload["primed"] == []
    assert payload["missing"] == []


# ---- collection command ----


def _write_csv(path: Path, rows: list[tuple[int, str, str]]) -> None:
    """Write a minimal MTGA-style CSV (Count,Name,Edition)."""
    lines = ["Count,Name,Edition,Condition,Language,Foil,Tag"]
    for qty, name, edition in rows:
        quoted = f'"{name}"' if "," in name else name
        lines.append(f"{qty},{quoted},{edition},Near Mint,English,,")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_collection_command_filters_by_color_and_type(
    mocker: pytest_mock.MockerFixture, tmp_path: Path
) -> None:
    csv = tmp_path / "coll.csv"
    _write_csv(
        csv,
        [
            (1, "Greasefang, Okiba Boss", "NEO"),
            (1, "Smuggler's Copter", "KLD"),
            (1, "Lightning Bolt", "M10"),
        ],
    )

    fake_results = [
        {
            "name": "Smuggler's Copter",
            "count": 1,
            "rarity": "rare",
            "cmc": 2,
            "type_line": "Artifact \u2014 Vehicle",
            "color_identity": [],
            "set": "kld",
        }
    ]
    filter_mock = mocker.patch("manascope.collection.filter_collection", return_value=fake_results)
    mocker.patch("manascope.scryfall.open_cache")

    result = runner.invoke(
        app,
        [
            "collection",
            "--collection",
            str(csv),
            "--color",
            "",
            "--type",
            "vehicle",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload == fake_results
    # The CLI must forward the user's filter args verbatim to filter_collection
    # — if it doesn't, agents can't trust the JSON output.
    kwargs = filter_mock.call_args.kwargs
    assert kwargs["color_identity"] == ""
    assert kwargs["type_substr"] == "vehicle"


# ---- build command ----


def test_build_command_invokes_build_run(mocker: pytest_mock.MockerFixture, tmp_path: Path) -> None:
    csv = tmp_path / "coll.csv"
    _write_csv(csv, [(1, "Plains", "FDN")])

    build_mock = mocker.patch("manascope.build.run")

    result = runner.invoke(
        app,
        [
            "build",
            "Greasefang,",
            "Okiba",
            "Boss",
            "--collection",
            str(csv),
            "--format",
            "brawl",
            "--top",
            "40",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    build_mock.assert_called_once()
    kwargs = build_mock.call_args.kwargs
    assert kwargs["commander_name"] == "Greasefang, Okiba Boss"
    assert kwargs["fmt"] == "brawl"
    assert kwargs["top"] == 40
    assert kwargs["json_flag"] is True
    assert [str(p) for p in kwargs["collection_paths"]] == [str(csv)]


def test_build_command_surfaces_value_errors(
    mocker: pytest_mock.MockerFixture, tmp_path: Path
) -> None:
    csv = tmp_path / "coll.csv"
    _write_csv(csv, [(1, "Plains", "FDN")])
    mocker.patch("manascope.build.run", side_effect=ValueError("nope"))

    result = runner.invoke(
        app,
        ["build", "Anybody", "--collection", str(csv)],
    )
    assert result.exit_code == 1
    assert "ERROR: nope" in result.stderr or "ERROR: nope" in result.stdout


# ---- verify --json / --fix ----


def test_verify_json_emits_structured_output(
    mocker: pytest_mock.MockerFixture, tmp_path: Path
) -> None:
    """verify --json must return a parseable JSON payload (no human prose).

    Closes the gap that AGENTS.md flagged about verify being the only
    command without a dense mode.
    """
    mocker.patch(
        "manascope.verify.verify_decklist",
        return_value={
            "checked": 1,
            "owned_count": 0,
            "missing_count": 1,
            "missing": [{"name": "Phantom", "rarity": "rare"}],
            "by_rarity": {"rare": ["Phantom"]},
        },
    )
    mocker.patch("manascope.scryfall.open_cache")

    decklist = tmp_path / "d.txt"
    decklist.write_text("1 Phantom (NEO) 1\n")
    csv = tmp_path / "c.csv"
    csv.write_text(
        "Count,Name,Edition,Condition,Language,Foil,Tag\n1,Foo,NEO,Near Mint,English,,\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "verify",
            "--decklist",
            str(decklist),
            "--collection",
            str(csv),
            "--json",
        ],
    )
    # Missing cards → exit 1, but stdout still has the JSON payload.
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["missing_count"] == 1
    assert payload["by_rarity"]["rare"] == ["Phantom"]


def test_verify_fix_rewrites_bad_printings(
    mocker: pytest_mock.MockerFixture, tmp_path: Path
) -> None:
    """verify --fix should rewrite ``(SET) CN`` for cards whose printing isn't cached
    but whose name is.
    """
    import sqlite3

    from manascope.scryfall import open_cache

    cache_db = tmp_path / "cache.db"
    conn: sqlite3.Connection = open_cache(cache_db)
    # Cache has Parhelion II under (war, 26) but the decklist refers to
    # the bogus printing (xyz, 999) — simulating my real-session mistake.
    payload = json.dumps(
        {"name": "Parhelion II", "set": "war", "collector_number": "26", "rarity": "rare"}
    )
    conn.execute(
        "INSERT INTO cards (set_code, collector_number, name, full_json) VALUES (?,?,?,?)",
        ("war", "26", "Parhelion II", payload),
    )
    conn.commit()
    conn.close()

    decklist = tmp_path / "deck.txt"
    decklist.write_text("1 Parhelion II (XYZ) 999\n", encoding="utf-8")
    csv = tmp_path / "c.csv"
    csv.write_text(
        "Count,Name,Edition,Condition,Language,Foil,Tag\n1,Parhelion II,WAR,Near Mint,English,,\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "verify",
            "--decklist",
            str(decklist),
            "--collection",
            str(csv),
            "--fix",
            "--json",
            "--cache",
            str(cache_db),
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["fix"]["rewritten"] == 1
    # The decklist file should now reference the cached printing.
    rewritten = decklist.read_text(encoding="utf-8")
    assert "Parhelion II (WAR) 26" in rewritten


def test_verify_fix_leaves_unresolvable_lines_untouched(
    mocker: pytest_mock.MockerFixture, tmp_path: Path
) -> None:
    """When the card's name isn't in the cache at all, --fix must NOT silently drop
    or mutate the line — it should be reported as unresolved.
    """
    from manascope.scryfall import open_cache

    cache_db = tmp_path / "cache.db"
    open_cache(cache_db).close()  # empty cache

    decklist = tmp_path / "deck.txt"
    original = "1 Phantom Card (XYZ) 999\n"
    decklist.write_text(original, encoding="utf-8")
    csv = tmp_path / "c.csv"
    csv.write_text(
        "Count,Name,Edition,Condition,Language,Foil,Tag\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "verify",
            "--decklist",
            str(decklist),
            "--collection",
            str(csv),
            "--fix",
            "--json",
            "--cache",
            str(cache_db),
        ],
    )
    assert result.exit_code == 1  # missing card
    payload = json.loads(result.stdout)
    assert payload["fix"]["rewritten"] == 0
    assert "Phantom Card" in payload["fix"]["unresolved_names"]
    # File untouched.
    assert decklist.read_text(encoding="utf-8") == original
