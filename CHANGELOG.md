# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[0.1.0]: https://github.com/melocene/ManaScope/releases/tag/v0.1.0
