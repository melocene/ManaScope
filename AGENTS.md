# ManaScope Agent Instructions

## Critical Rules
- Source of truth: `decks/<format>/<deck>.txt`; cache is never authoritative.
- Use `uv run manascope <cmd>` for ManaScope CLI work. Do not call the CLI via bare `python`.
- Do not modify decklists unless the user explicitly asks. Put proposed swaps in the review file.
- Do not print full decklists or full EDHREC lists in chat.
- Confirm collection type before deck work: paper ManaBox vs MTGA Arena.
- Ignore directories starting with `_` or `.`, prices, budget, and paper rarity unless explicitly relevant.
- Never invent card attributes, set codes, collector numbers, legality, land speed, or Arena rarity.
- Card data must come from current-session `lookup --brief --json`; never rely on memory, name, or art.
- Before describing a card's rules text, type, mechanics, or interactions in chat or in a review, you MUST have read its `oracle_text` from a current-session `lookup --brief --json` (not `--minimal`, which omits oracle text). Do not paraphrase from memory.
- Batch work: one `lookup` with all needed names; one combined CSV search pattern; one `prime` per commander.
- Never redirect command output to files or pipe through `head`, `tail`, `jq`, or `python -c`; dense modes are sized for direct context reads.
- When modifying gitignored files (e.g. `collections/`, `.cache/`), use `edit_file` per change instead of shell scripts so edits are reviewable in the editor's diff view.

## Agent Output Modes
Never use rich/human output in agent sessions.

| Command | Required mode |
|--|--|
| `analyze` | `--json` |
| `review` | `--agent` |
| `pipeline` | native JSON; includes `verify` when `--collection` is passed; `--summary` for one-line status |
| `edhrec` | `--json --top N` |
| `lookup` | `--brief --json`; `--minimal` for trimmed JSON (drops oracle text) |
| `prime` | `--quiet`; `--json` for primed-card report |
| `verify` | `--json`; optional `--fix` and `--printings` (paper-only, exact `(SET) CN` match against non-foil collection rows) |
| `collection` | `--json` |
| `build` | `--json` |
| `hand` | `--agent` for dense one-line-per-hand/aggregate; `--json` for full structured output; `--hands N` for N individual hands in one call |

Useful flags: `--format commander|brawl|standardbrawl`, `--top N`, `--strict`.

## Validation
Run before declaring code changes complete:

`uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run ty check src/ && uv run python -m pytest tests/`

Slow ReDoS tests on demand:

`uv run python -m pytest tests/ -m slow`

## Decklist Format
- All lines: `<qty> <name> (<set>) <collector#>`.
- Commander paper: first line is commander, no headers, full DFC names, exactly 100 cards.
- Brawl: `Commander` and `Deck` headers, front-face names only, exactly 100 cards.
- Standard Brawl: `Commander` and `Deck` headers, front-face names only, exactly 60 cards.
- After every deck edit, run `analyze --json` and confirm `cards.ok`.

## Card Data Rules
- Always read `type_line`, `land_speed`, `subtypes`, `color_identity`, `on_arena`, and `arena_rarity` when relevant.
- For Arena wildcard math, trust `arena_rarity`, not paper `rarity`.
- Arena ownership is shared across decks: 1 owned copy covers a card in every singleton-format deck (Brawl, Historic Brawl, Commander) simultaneously. Only Standard/Historic/Timeless constructed need up to 4 copies. When recommending crafts, treat ownership of ≥1 copy as fully sufficient for singleton formats and never recommend crafting additional copies for Brawl-only use.
- Brawl on Arena is 1v1 with random matchmaking; there are no pods, no pre-arranged opponents, and no "local meta" to read. Do not recommend meta-call cards or sideboard-style swaps based on expected opponents. Evaluate cards against the broad Brawl ladder, not a known group.
- When evaluating wildcard spend, always grep the collection CSV for each candidate first (handling quoted comma-names like `"Sheoldred, the Apocalypse"`); do not assume a card is missing without checking.
- Check commander color identity before recommending or adding cards.
- Evaluate lands like spells: speed, subtypes, fixing, utility, and additive type changes.
- If collection data looks stale, ask the user to re-export before substituting alternatives.
- Use front-face names only for DFCs/Sagas/Adventures in Brawl and Standard Brawl; paper Commander may use full names.

## Existing Deck Workflow
1. Resolve commander from the decklist.
2. `uv run manascope prime "<Commander>" --quiet`
3. `uv run manascope edhrec "<Commander>" --json --top N`
4. `uv run manascope pipeline --decklist <path> --collection <csv>`
5. If `review.stats.skipped > 0`, prime again, then rerun pipeline.
6. If printings look wrong, run `uv run manascope verify --decklist <path> --collection <csv> --fix --json`.
7. To catch printing typos that resolve to *some* owned copy but not the listed `(SET) CN`, run `uv run manascope verify --decklist <path> --collection <csv> --printings --json`. ManaBox CSVs only; MTGA exports silently fall back to name-only verification.
8. Batch `lookup --brief --json` for all unfamiliar cards, gaps, lands, and wishlist candidates.
9. Write/update the review using `docs/review-template.md`.
10. Re-run pipeline after applied deck edits.

## New Deck Workflow
1. `uv run manascope prime "<Commander>" --quiet`
2. `uv run manascope build "<Commander>" --collection <csv> --format <fmt> --json --output decks/<fmt>/<deck>.txt`
3. Inspect JSON gaps and unowned candidates.
4. Use `uv run manascope collection --collection <csv> --color <CI> --type <kw> --legal <fmt> --json` for owned alternatives.
5. Run `uv run manascope pipeline --decklist <path> --collection <csv>`.

## Review Files
- Place reviews in the same directory as the deck file, named `<commander>-review.md` (e.g. `decks/brawl/greasefang-review.md`).
- Keep reviews terse and human-readable.
- Include swaps, owned omissions, wishlist, mana-base notes, combo lines, wildcard needs, final verdict, and deck path.
- Do not include full decklists or full EDHREC lists.

## Collections
- Paper ManaBox and MTGA Arena CSVs differ; confirm which one the user provided.
- Prefer `collection --json`, `verify --json`, and `pipeline` over manual CSV parsing.
- If manual parsing is unavoidable, inspect headers first; see `docs/collections.md`.

## Project Layout
- Code: `src/manascope/`
- Decks: `decks/<format>/`
- Collections: `collections/`
- Cache: `.cache/cache.db`
- Prefix file paths with `ManaScope/` in read/write/search tools.
- In terminal, work from the project root.
- Format auto-detects from `decks/commander/`, `decks/brawl/`, and `decks/standardbrawl/`; use `--format` outside those paths.
