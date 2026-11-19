# ManaScope Agent Instructions

## Hard Rules
These override everything below.

1. Run the CLI as `just manascope <cmd>`. If `just` is not installed, use `UV_CACHE_DIR=.cache/uv uv run manascope <cmd>`; plain `uv run` fails in sandboxes where `~/.cache/uv` is read-only. Never call the CLI via bare `python`. Commands below use the `just` form; read any `uv run manascope ...` hint from the CLI or docs the same way.
2. Never modify decklists unless the user explicitly asks; put proposed swaps in the review file. Decklists (`decks/<format>/<deck>.txt`) are the source of truth; the cache never is.
3. Never state card facts from memory, name, or art: rules text, type, mechanics, interactions, legality, set code, collector number, land speed, or Arena rarity. Take them from a current-session `lookup --brief --json`. Before describing what a card does, read its `oracle_text` (`--minimal` omits it).
4. Never print full decklists or full EDHREC lists in chat or reviews.
5. Never pipe or redirect ManaScope CLI output (`head`, `tail`, `jq`, `python -c`, `>`). Agent output modes are sized to be read directly.

## Environment
- Network is blocked by default. Request only the hosts needed: `json.edhrec.com` / `api.scryfall.com` for card and EDHREC fetches (`prime`, `edhrec`, `lookup`, stale cache refreshes); `pypi.org` and `files.pythonhosted.org` for dependency syncs.
- `collections/` and `decks/` are gitignored, so search/list tools show them as empty. Check in the terminal (`ls collections/`, `head -1 collections/<file>.csv`) before concluding a file is missing. Shell inspection of files is fine; rule 5 covers CLI output only.
- Edit gitignored files (`collections/`, `.cache/`) with `edit_file`, one change per call, not shell scripts, so edits appear in the diff view.
- Prefix tool paths with `ManaScope/`; run terminal commands from the project root.
- Ignore directories starting with `_` or `.`, and ignore prices, budget, and paper rarity unless the user raises them.

## Deck Work

### Before starting
- Confirm the collection type: paper ManaBox or MTGA Arena. Schemas differ; see `docs/collections.md`.
- Format auto-detects from `decks/commander/`, `decks/brawl/`, and `decks/standardbrawl/`; pass `--format` elsewhere.
- Batch: one `lookup` for all names, one combined CSV grep pattern, one `prime` per commander.

### Output modes
Never use rich/human output.

| Command | Mode |
|--|--|
| `analyze` | `--json` |
| `review` | `--agent` |
| `pipeline` | native JSON (includes `verify` when `--collection` is passed); `--summary` for one line |
| `edhrec` | `--json --top N` |
| `lookup` | `--brief --json`; `--minimal` drops oracle text |
| `prime` | `--quiet`; `--json` for a primed-card report |
| `verify` | `--json`; optional `--fix`, `--printings` |
| `collection` | `--json` |
| `build` | `--json` |
| `hand` | `--agent` (one line per hand); `--json` (full); `--hands N` |

Other useful flags: `--format commander|brawl|standardbrawl`, `--top N`, `--strict`.

### Existing deck
1. Resolve the commander from the decklist.
2. `just manascope prime "<Commander>" --quiet`
3. `just manascope edhrec "<Commander>" --json --top N`
4. `just manascope pipeline --decklist <path> --collection <csv>`
5. If `review.stats.skipped > 0`, prime again and rerun the pipeline.
6. Printing problems (many owned cards showing as gaps usually means bad `(SET) CN` pairs):
   - `just manascope verify --decklist <path> --collection <csv> --fix --json`
   - Add `--printings` to catch typos that still match some owned copy. ManaBox only; MTGA falls back to name-only.
7. One batched `lookup --brief --json` for every unfamiliar card, gap, land, and wishlist candidate.
8. Write or update the review (see Review Files).
9. After applied deck edits, rerun the pipeline.

### New deck
1. `just manascope prime "<Commander>" --quiet`
2. `just manascope build "<Commander>" --collection <csv> --format <fmt> --json --output decks/<fmt>/<deck>.txt`
3. Inspect the JSON gaps and unowned candidates.
4. Owned alternatives: `just manascope collection --collection <csv> --in-identity <CI> --type <kw> --legal <fmt> --json`
5. `just manascope pipeline --decklist <path> --collection <csv>`

### Decklist format
- Every line: `<qty> <name> (<set>) <collector#>`.
- Commander (paper): commander on the first line, no headers, full DFC names, exactly 100 cards.
- Brawl / Standard Brawl: `Commander` and `Deck` headers, front-face names only for DFCs, Sagas, and Adventures, exactly 100 / 60 cards.
- After every deck edit, run `analyze --json` and confirm `cards.ok`.

### Card evaluation
- Read `type_line`, `subtypes`, `color_identity`, `land_speed`, `on_arena`, and `arena_rarity` as relevant.
- A card's `color_identity` must be a subset of the commander's. Review/build can silently skip out-of-identity cards, so check before recommending or adding.
- Evaluate lands like spells: speed, subtypes, fixing, utility, and additive type changes. Prefer conditional or shock duals over tapped duals when owned and legal.
- Ownership: `collection` skips cards missing from the Scryfall cache, so grep the collection CSV before calling a card unowned or spending a wildcard (handle quoted comma names like `"Sheoldred, the Apocalypse"`). If the data looks stale (e.g. the user just crafted a card), ask for a fresh export instead of substituting.

### Arena
- Wildcard math uses `arena_rarity`, never paper `rarity`; they can differ (e.g. Foundry Inspector is paper-common but Arena-uncommon in KLR/BRR).
- One owned copy covers every singleton deck (Brawl, Historic Brawl, Commander). Never recommend extra copies for Brawl; only Standard/Historic/Timeless constructed need up to 4.
- Arena Brawl is 1v1 with random matchmaking: no pods, no local meta. Judge cards against the broad ladder; no meta calls or sideboard-style picks.

### EDHREC lift
- EDHREC replaced synergy % with **lift**: how often decks with this commander run the card compared with random chance. `1.0` = no association, `3.2` = 3.2x as often, below `1.0` = less often. It is a ratio, not a percentage.
- Write it as `3.2x lift`; never call it "synergy" or show it as `%`.
- Weigh lift with `inclusion`: high lift can be a niche pick. Staples like Sol Ring sit near `1.0` because everyone plays them, so low lift alone is not a cut signal.
- `"lift": null` plus a `synergy` key means the cached page predates lift. Label it legacy synergy and never compare it with lift.

### Review files
- Save next to the deck as `<commander>-review.md` (e.g. `decks/brawl/greasefang-review.md`), following the sections in `docs/review-template.md`. Keep it terse.
- Every swap names both the card going OUT and the card coming IN. Without a concrete cut, label the card as a flex/bench consideration, not a swap.

## Code Changes
- Code: `src/manascope/`; tests: `tests/`; cache: `.cache/cache.db`.
- Before declaring changes complete, run `just check` (ruff, format check, ty, pytest). Slow ReDoS tests: `just test-slow`. Without `just`, run the commands in the README's Testing & Validation section, each prefixed with `UV_CACHE_DIR=.cache/uv`.
