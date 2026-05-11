# Agent Notes and Gotchas

These notes capture recurring mistakes. Keep `AGENTS.md` short; read this file only when a task needs deeper context.

## Printing and Ownership

- Do not invent set codes or collector numbers. Copy `set` and `collector_number` from `lookup --brief --json`, grep owned printings from the collection, or use `verify --fix`.
- If many owned cards appear as gaps, the decklist may have bad `(SET) collector_number` pairs.
- If the user recently crafted a card but the CSV says it is unowned, ask for a fresh export before recommending substitutes.

## Arena Details

- Arena rarity can differ from paper rarity. `Foundry Inspector` is paper-common in some printings but Arena-uncommon in KLR/BRR.
- For Arena wildcard math, always use `on_arena` and `arena_rarity` from `lookup --brief --json`.
- Brawl and Standard Brawl imports need front-face names only for DFCs, Sagas, and Adventures.

## Color Identity

Out-of-identity recommendations can be silently skipped by review/build flows. Always verify a recommended card's `color_identity` is a subset of the commander's color identity before adding or recommending it.

## Lands

Evaluate lands like spells:

- `land_speed`
- `subtypes`
- color fixing
- utility text
- additive type modifications

Prefer conditional or shock duals over tapped duals when possible, assuming ownership and legality are confirmed.
