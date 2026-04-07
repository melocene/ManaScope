# Contributing to ManaScope

All contributions are welcome. Bug reports, documentation fixes, and code changes all make the project better. None are too small to matter.

## Ways to Contribute

There are many ways to get involved and all of them are appreciated. A few ideas to get you started:

- Found a bug? Open an issue with steps to reproduce, the command you ran, and what you expected to see.
- Something in the README, `AGENTS.md`, or elsewhere unclear or wrong? A documentation fix is a real contribution.
- Have a feature idea? Open an issue to discuss it before writing code. Fixes for existing open issues can go straight to a PR.

Have a question, a suggestion, or just curious about why something works the way it does? Open an issue. Maintainers are happy to chat.

## Getting Started

See the [README](README.md) for installation, project layout, and how to run the tool. The full validation suite is documented under [Testing & Validation](README.md#testing--validation).

## Development Guidelines

### Branch target

Please open all pull requests against the `dev` branch, not `main`. The `main` branch is kept stable and should always reflect the current documented release. Work is merged to `main` from `dev` when it is ready to ship.

### Tests

The full test suite runs on every push via CI. Running it locally before you push is a good way to catch failures early. If you add new functions or methods, writing tests for them is encouraged. If you change existing behaviour, updating the relevant tests helps. Tests and source files should stay in logical units where reasonable. For example, `tests/test_deck.py` covers `deck.py`. If any of this is skipped, we may follow up during review.

### Changelog

If you make a notable change, adding a line to [`CHANGELOG.md`](CHANGELOG.md) under the `Unreleased` section is appreciated but not required. It will be reviewed and tidied before any release. Please do not change the version number.

### Code style

ManaScope uses [`ruff`](https://docs.astral.sh/ruff/) for linting and formatting. CI enforces this automatically. To check locally:

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
```

To auto-fix formatting:

```bash
uv run ruff format src/ tests/
```

## Copyright and Card Data

Please do not include any copyrighted material in your contributions. This means no card frames, card artwork, set symbols, or other proprietary Wizards of the Coast or third-party imagery.

Card names, mana costs, and other game data, as they appear in this project, are factual information rather than creative works and are not subject to copyright in that form. That is the extent of what belongs here. ManaScope fetches only the minimal structured data it needs via the [Scryfall API](https://scryfall.com/docs/api). There is no reason to store or bundle any additional card data in the repository.

## External Services

ManaScope makes HTTP requests to [Scryfall](https://scryfall.com/docs/api) and [EDHREC](https://edhrec.com/terms). Scryfall has documented API guidelines; EDHREC does not expose a public API, so the project uses its JSON data endpoints as a convenience for personal, noncommercial deckbuilding. In both cases the code is designed to be a polite, low-volume client.

The existing network code already implements these good-citizen measures:

- `User-Agent` and `Accept` headers are set on every request, as Scryfall requires.
- Both services use a consistent 300 ms delay between requests.
- Scryfall card data is cached permanently (no TTL); a card is only fetched once unless the cache is cleared.
- Scryfall requests are batched (up to 75 cards per call) to minimise round-trips.
- EDHREC commander pages are cached with a 14-day TTL, so each page is fetched at most once every two weeks.

If your contribution touches the network-call code in `scryfall.py` or `edhrec.py`, please preserve or improve these measures. Do not bypass the caching layer, remove the delays, or change the `User-Agent` to something inaccurate or blank. Changes that increase request frequency or remove rate-limiting will be asked to be revised during review.

## AI Policy

We're not anti-AI, and use it ourselves. The short version: understand the code you submit, test it yourself (automated suite *and* running the application), and disclose the tools you used in your PR description.

See [`AI_POLICY.md`](AI_POLICY.md) for the full rules.
