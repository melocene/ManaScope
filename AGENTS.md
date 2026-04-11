# ManaScope Agent Instructions

## Core Rules
- **Source of Truth**: `decks/<format>/<deck>.txt`. Cache is NOT authoritative.
- **Commands**: Always use `uv run manascope <cmd>`. NEVER `python`.
- **Python 3 Exception Syntax**: Both `except (TypeError, ValueError):` and `except TypeError, ValueError:` are valid Python 3 — the bare-comma form creates an implicit tuple. Do NOT flag bare-comma except clauses as bugs or Python 2 remnants.
- **Validation**: `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run ty check src/ && uv run python -m pytest tests/`
- **Card Data**: ALL attributes MUST come from `uv run manascope lookup <name> --brief --json` in the current session. NEVER assume behavior from memory/name/art.
  - Always read `type_line`, `land_speed`, and `subtypes`. Never infer land entry conditions. Evaluate additive type modifications carefully.
- **Batching**: All needed names are already in context from prior tool outputs — collect them and call once. NEVER make repeated single-item calls.
  - `lookup`: ONE call with all card names — `uv run manascope lookup "Card1" "Card2" "Card3"`
  - CSV ownership: ONE search with a combined name pattern — `"Card1|Card2|Card3"` — never search card by card
  - `prime`: ONE call per commander only — not a single-card fetch tool; use `lookup` for individual cards
- **Ignore**: Directories starting with `_` or `.`, prices, budget, rarity.
- **Collections**: Confirm whether the collection is a paper (ManaBox) or Arena digital export before proceeding.
- **Boundaries**: Do not modify decklists unprompted — swaps go in the review file. Changes can be applied on explicit user request; note this once if helpful but do not repeat. Do not print raw decklists or full EDHREC lists in chat.
- **Flags**:
  - `--json`: pure JSON output — `edhrec`, `analyze`, `review`, `lookup` *(`pipeline` outputs JSON natively — flag not needed)*
  - `--agent`: dense machine-readable text optimized for LLM context — `analyze`, `review`
  - `--compact`: reduced decorative output, still human-readable — `analyze`, `review`
  - `--quiet` / `-q`: summary line only — `edhrec`, `prime`, `lookup`
  - `--brief`: `lookup` only — never combine with `--quiet`
  - `--format (commander|brawl|standardbrawl)`: override auto-detected format — `analyze`, `review`, `pipeline`
  - `--top INTEGER`: EDHREC cards to evaluate, default 80 — `review`, `pipeline`, `prime`

## Decklist Format Rules
- **Line format** (all formats): `<qty> <name> (<set>) <collector#>` — e.g. `1 Isolated Chapel (OTC) 301`. Pick any owned printing unless directed otherwise.
- **Commander (Paper)**: Line 1 = Commander (no headers). Full DFC names (`Front // Back`). Exactly 100 cards.
- **Brawl**: `Commander` and `Deck` headers required. Front-face only for DFCs/Adventures. Exactly 100 cards.
- **Standard Brawl (Arena)**: `Commander` and `Deck` headers required. Front-face only for DFCs/Adventures. Exactly 60 cards.

## Tools & Layout
- **Pathing**: Prefix all file paths with `ManaScope/` in read/write/search tools. In terminal, confirm working directory first.
- **Project**: `src/manascope/` (code) · `decks/<format>/` (decklists) · `.cache/cache.db` (data) · `collections/` (CSVs)
- **Format detection**: Auto-detected from the decklist directory path (`decks/commander/`, `decks/brawl/`, `decks/standardbrawl/`). Use `--format` to override if the decklist is outside this structure.

## Standard Workflow (Commander / Brawl)
1. **Resolve Commander**: Paper format — line 1 is the commander. Arena format — line 1 is the `Commander` header, line 2 is the card. Use `lookup` if unsure.
2. **Prime Cache**: `uv run manascope prime "Cmdr Name" --quiet` *(fetches EDHREC data + pre-warms Scryfall card cache)*
3. **Get Baseline**: `uv run manascope edhrec "Cmdr Name" --json` *(reads from cache)*
4. **Run Pipeline**: `uv run manascope pipeline --decklist <path> --collection <csv>` *(If `stats.skipped > 0` in output: `prime --quiet`, then repeat.)*
5. **Verify Ownership**: `uv run manascope verify --decklist <path> --collection <csv>`
6. **Batch-Lookup**: ONE call covering all unfamiliar cards, gaps (including lands), and wishlist candidates before analysis.
7. **Report**: Write `decks/<format>/<deck>-review.md`. Verify "In" cards are owned via ONE combined CSV search (all names in a single pattern). Confirm legality via `lookup --brief --json` — check that `legalities.<format>` equals `"legal"` for each recommended card.
8. **Validate**: Re-run pipeline if changes are applied.

## Review File (`<deck>-review.md`)
Must contain:
- Snapshot (current deck vs. EDHREC baseline)
- Mana base & curve analysis
- Synergy assessment (keep/cut reasoning)
- **Swap Table**: Single Out/In table covering both spells and lands. Give equal priority to lands from `gaps_owned`.
- Before/After metrics & Wishlist

## Land Swap Guidance
- Evaluate lands on the same criteria as spells: fit, `land_speed`, `subtypes`, and utility.
- Prefer conditional/shock duals over tapped duals where possible.
- Pull candidates from pipeline `gaps_owned`, verify ownership via a single combined CSV search, then batch `lookup` before recommending.

## Collection CSV Formats
Paper and Arena digital collections use different schemas — do not confuse them.

- **Paper (ManaBox)**: Key columns — `Name` (0), `Set code` (1), `Collector number` (3), `Foil` (4), `Quantity` (6), `Scryfall ID` (8).
- **Arena (MTGA)**: Schema varies and may include Arena-exclusive cards — always inspect the header row before assuming column indices.
