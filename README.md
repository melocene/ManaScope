# ManaScope

ManaScope is a CLI tool for analyzing Magic: The Gathering decklists—cross-referencing them against EDHREC community data and verifying them against your personal collection.

Whether you're tuning a Commander deck or an Arena Brawl list, it gives you a clear picture of your mana base, synergy gaps, and potential upgrades—including which ones you already own.

## Table of Contents
- [Development Philosophy & AI Policy](#development-philosophy--ai-policy)
- [Getting Started](#getting-started)
  - [Requirements](#requirements)
  - [Installation](#installation)
  - [Project Layout](#project-layout)
  - [Setting Up Your Collection](#setting-up-your-collection)
  - [Decklist Format](#decklist-format)
- [Features & Workflows](#features--workflows)
  - [The Human Workflow (CLI)](#the-human-workflow-cli)
  - [The AI Workflow](#the-ai-workflow)
- [Testing & Validation](#testing--validation)
- [Versioning](#versioning)
- [Supported MTG Formats](#supported-mtg-formats)

## Development Philosophy & AI Policy

Most of ManaScope's code was written by AI. What separates it from a "vibe-coded" project is the human work underneath: deliberate architecture decisions, continuous code review, and extensive real-world testing across multiple formats and decklists before anything shipped. The AI wrote fast; a human steered the design.

We welcome all contributions. The short version: understand the code you submit, test it yourself, and disclose any AI tools you used. See [`AI_POLICY.md`](AI_POLICY.md) for the full rules.

## Getting Started

### Requirements
- **Python 3.14+** — ManaScope targets the latest Python release; older versions may work but aren't actively supported
- **[`uv`](https://docs.astral.sh/uv/)** — dependency management and task runner

### Installation
```bash
git clone https://github.com/melocene/ManaScope
cd ManaScope
uv sync
```

No traditional install step required. `uv run` manages the virtual environment automatically — `uv sync` pre-populates it, but `uv run manascope <command>` will do so on first use if you skip it.

All commands are run via `uv run manascope <command>`.

### Project Layout

```
ManaScope/
├── .cache/            # SQLite cache — auto-created on first run
├── collections/       # Your collection CSVs go here
├── decks/
│   ├── commander/     # Paper Commander decklists
│   ├── brawl/         # Arena Brawl decklists
│   └── standardbrawl/ # Arena Standard Brawl decklists
└── src/               # Source code
```

The cache is managed automatically. ManaScope fetches card data from Scryfall on demand and stores it locally, so subsequent runs don't hit the network for cards it has already seen.

### Setting Up Your Collection

ManaScope reads collection data from a CSV file exported by **[ManaBox](https://manabox.app/)**, which is the recommended tool for tracking a physical card collection.

To export from ManaBox:
1. Open the app and navigate to your collection.
2. Tap the menu and select **Export → Export as CSV**.
3. Save the file into the `collections/` directory (e.g., `collections/Primary.csv`).

Pass the path to any command that accepts `--collection`.

### Decklist Format

Decklists are plain `.txt` files stored under `decks/<format>/`.

**Commander (Paper / MTGO)**
- No section headers. The first line is the commander.
- Use full card names including both faces for DFCs: `Delver of Secrets // Insectile Aberration`
- Exactly 100 cards.

**Brawl / Standard Brawl (Arena)**
- Requires `Commander` and `Deck` section headers.
- Use front-face names only for DFCs and Adventures.
- Exactly 100 cards.

## Features & Workflows

ManaScope is built to be useful on its own from the command line. It also exposes structured JSON output designed for AI agents that want to go further with interpretive analysis.

### The Human Workflow (CLI)

These commands give you immediate, structured data about your deck and collection.

**`edhrec`** — Pull EDHREC community data for a commander: type distributions, mana curve, top synergy cards, combos, and themes.
```bash
uv run manascope edhrec "Krenko, Mob Boss"
```

**`analyze`** — Break down your mana base: land counts, land speeds (untapped / shock / conditional / tapped), colour balance vs. pip demand, mana rocks and dorks, and curve distribution.
```bash
uv run manascope analyze --decklist decks/commander/krenko.txt
```

**`review`** — Find synergy gaps between your deck and EDHREC recommendations. Pass `--collection` to split results into cards you own vs. cards you don't.
```bash
uv run manascope review --decklist decks/commander/krenko.txt
uv run manascope review --decklist decks/commander/krenko.txt --collection collections/Primary.csv
```

**`verify`** — Check every card in your decklist against your collection CSV. Flags missing cards by rarity and handles DFCs. Requires `--collection`.
```bash
uv run manascope verify --decklist decks/commander/krenko.txt --collection collections/Primary.csv
```

**`lookup`** — Fetch authoritative Scryfall card data: mana cost, type line, rules text, land speed, produced mana, and more.
```bash
uv run manascope lookup "Skirk Prospector" "Goblin Recruiter" --brief
```

With these commands you can identify mana base problems, see which high-synergy staples you're missing (and which you already own), and confirm you can build the deck before sleeving up.

### The AI Workflow

Deciding *which specific card* comes out for *which specific card* coming in—and *why*—is inherently interpretive work. That's where an LLM adds the most value on top of ManaScope's raw data.

**`pipeline`** — Runs `analyze` and `review` together and outputs a single compact JSON payload built for AI consumption. Pass `--collection` to include ownership data.
```bash
uv run manascope pipeline --decklist <path> [--collection <csv>]
```

**`prime`** — Pre-warms the local Scryfall cache with EDHREC-recommended cards for a commander. Useful before running the pipeline to avoid mid-analysis fetch delays.
```bash
uv run manascope prime "Krenko, Mob Boss" --quiet
```

Most commands also accept `--json`, `--agent`, and `--compact` flags for varying levels of machine-readable output. An AI agent consuming this data can produce a `<deck>-review.md` file with a concrete swap table, mana analysis, and strategic assessment.

*(For the full agent workflow, see [`AGENTS.md`](AGENTS.md).)*

## Testing & Validation

All code—regardless of how it was authored—must pass the full validation suite. ManaScope uses `ruff` for linting and formatting, `ty` for type checking, and `pytest` for unit tests. CI enforces all four on every push.

To run locally:
```bash
uv run ruff check src/ tests/          # Linting
uv run ruff format --check src/ tests/ # Formatting
uv run ty check src/                   # Type checking
uv run python -m pytest tests/         # Unit tests
```

## Versioning

ManaScope loosely follows [Semantic Versioning](https://semver.org/). As an application rather than a library, version bumps reflect meaningful user-facing changes rather than strict API contracts. See [CHANGELOG.md](CHANGELOG.md) for release notes.

## Supported MTG Formats
- Commander (Paper / MTGO)
- Brawl (MTG Arena)
- Standard Brawl (MTG Arena)
