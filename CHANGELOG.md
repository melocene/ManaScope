# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- `build` no longer emits `Plains (<commander_set>) 1` for basic lands. The old behaviour resolved to whatever card actually sat at collector number 1 of the commander's set (e.g. `Ancestral Katana` for NEO, `Coppercoat Vanguard` for MAT, `Sire of Seven Deaths` for FDN), silently corrupting downstream `analyze`/`pipeline` runs by reporting 0 lands and bucketing the basics under whatever type that card was. Basics now use a stable real printing (`ONE 267`-`ONE 271`) via the new `BASIC_PRINTING` constant in `manascope.build`.
- `build --output <path>` is no longer suppressed by `--json`. The two flags are now orthogonal: when both are passed the decklist is written to disk *and* the JSON report is emitted on stdout. The report also gains a new `output_path` key. This restores the documented `build --json --output X` → `pipeline --decklist X` workflow.


## [0.2.0] - 2026-05-05

### Added
- `verify --printings` flag — paper-only strict mode that verifies each decklist line's exact `(SET) collector#` matches a non-foil printing in the collection, catching printing typos that pass the name-only check (e.g. `Sol Ring (CMM) 410` when only `Sol Ring (ECC) 58` is owned). Adds `wrong_printing_count` and `wrong_printing` keys to the JSON payload. ManaBox CSVs only; MTGA exports silently fall back to name-only verification.
- `load_collection_printings` / `load_collections_printings` — public helpers in `manascope.collection` that return `set[(name, set, cn)]` tuples for non-foil owned printings. Pass `include_foil=True` to surface foils as well.
- Multi-collection support — `--collection` now accepts multiple paths and merges the results (sums counts, unions printings) before running verify, review, pipeline, build, or collection commands.
- `parse_decklist(strict=True)` and `--strict` CLI flag — fail (exit code 1) on any malformed decklist line instead of silently skipping it. Available on `verify`, `analyze`, and `pipeline`.
- Agent-friendly output modes across the CLI: `--agent` (review), `--minimal` (lookup, drops oracle text), `--summary` (pipeline one-liner), and consistent `--json` / `--quiet` / `--brief` flags. Designed for compact, parser-friendly output.
- `iter_all_cards` helper in `manascope.scryfall` for efficient full-cache iteration (used by review/synergy passes).
- ReDoS regression test suite under `tests/test_review_redos.py`, gated behind the `slow` pytest marker. Exercises potentially catastrophic regex inputs in a subprocess with a hard timeout.
- CodeQL static analysis configuration for required workflows.

### Changed
- HTTP responses (Scryfall, EDHREC) now stream with early abort on a size cap, preventing runaway downloads from a misbehaving upstream.
- SQLite cache uses WAL pragmas for safer concurrent reads; cache writes use `executemany` upsert and batched IN-queries for bulk lookups.
- Per-card memoization added for `oracle_text`, `type_line`, `produced_mana`, and `land_speed` derivations — measurable speedups on review/build runs over large caches.
- `prime` now uses a single SQLite connection across the whole run with `try/finally` close on failure paths.
- 404 responses from Scryfall are rate-limited to avoid hammering the API on long batch lookups.
- Hot-path regular expressions are now compiled once at module import.
- `requests.Session` instances are closed on every return path, including error branches.
- `REQUEST_TIMEOUT` is unified across `manascope.scryfall` and `manascope.edhrec`.
- CI workflow triggers slimmed down to reduce redundant runs.
- Decklist formatting rules clarified in `AGENTS.md` for script compatibility (consistent `<qty> <name> (<set>) <cn>` format, including basics).
- Headers are suppressed in agent / machine-readable runs to keep JSON payloads parseable.

### Fixed
- `verify` no longer reports a deck as fully owned when its listed `(SET) CN` printings aren't actually in the collection. Previously, any matching name passed verification regardless of printing; the new `--printings` flag opts into the stricter check, with name-only behaviour preserved as the default for backward compatibility with MTGA collections.
- Incorrect review path resolution under certain working-directory configurations.
- Schema-safe verify when the cache database exists but is empty / missing tables.
- Format-rule typo in decklist parsing that affected a niche edge case.
- Parenthesized except tuple in `collection.lookup_rarity` — Python 3.14 syntax compliance.
- `requests.Session` resource leak when fetch raised mid-run.

### Security
- Documented reliance on `certifi`'s bundled CA store for HTTPS verification in `SECURITY.md`.

## [0.1.0] - 2026-04-07

### Added
- `analyze` command — mana base breakdown: land counts, land speeds, colour balance vs. pip demand, mana rocks/dorks, and curve distribution
- `review` command — synergy gap analysis against EDHREC recommendations, with owned/not-owned split when a collection CSV is provided
- `pipeline` command — combined `analyze` + `review` in a single compact JSON payload optimised for AI consumption
- `prime` command — pre-warms the local Scryfall cache with EDHREC-recommended cards for a commander
- `verify` command — checks every card in a decklist against a collection CSV, flagging missing cards
- `lookup` command — fetches authoritative Scryfall card data for one or more cards
- `edhrec` command — pulls EDHREC community data for a commander
- Support for Commander (paper/MTGO), Brawl (Arena), and Standard Brawl (Arena) formats
- SQLite-backed cache for Scryfall card data (permanent) and EDHREC pages (14-day TTL)
- `--json`, `--agent`, `--compact`, `--quiet`, and `--brief` output flags
- CI via GitHub Actions: ruff lint, ruff format, ty type check, pytest
- CodeQL static analysis on push and weekly schedule
- Dependabot for weekly dependency updates
