# Collection CSV Notes

Use this only when manual CSV inspection is unavoidable. Prefer ManaScope commands first:

- `uv run manascope collection --collection <csv> --json`
- `uv run manascope verify --decklist <path> --collection <csv> --json`
- `uv run manascope pipeline --decklist <path> --collection <csv>`

## Collection Types

Always confirm whether the user provided a paper or Arena collection.

### Paper: ManaBox

Known key columns:

| Field | Column index |
|--|--:|
| `Name` | 0 |
| `Set code` | 1 |
| `Collector number` | 3 |
| `Foil` | 4 |
| `Quantity` | 6 |
| `Scryfall ID` | 8 |

The `Set code`, `Collector number`, and `Foil` columns are what `verify --printings`
uses to perform strict per-printing matching. `Foil` values are typically `normal`,
`foil`, or `etched`; only `normal` is included by default.

### Arena: MTGA

MTGA export schemas can vary and may include Arena-exclusive cards. Always inspect the header row before assuming column positions.

For Arena wildcard reasoning, use `on_arena` and `arena_rarity` from `lookup --brief --json`; do not use paper rarity.
