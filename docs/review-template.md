# Deck Review Template

Keep reviews terse and human-readable. The user decides what to change: give them the evidence and tradeoffs to choose, not verdicts. Do not include full decklists or full EDHREC lists.

```markdown
# <Commander> — <Format> Review

**Format:** <commander|brawl|standardbrawl>
**Commander:** <Name> `<mana cost>` — <type line>
**Strategy:** <one-sentence game plan>

## TL;DR
<one paragraph: ready-to-import? wildcards needed? key combos?>

## Snapshot
| Metric | Value | EDHREC Baseline |
|--|--|--|
<cards count, lands, color sources, curve peak, key archetype counts>

## Combo Lines
<table or list of primary win conditions, marking which pieces are owned>

## Wildcards to Spend
<table: Card | Arena Set | Rarity | Why — only cards with on_arena=true>

## Proposed Swaps
<table: Priority | OUT | IN | Evidence | Tradeoff. Evidence: lift/inclusion for both cards and the role each fills per its oracle text. Tradeoff: what the deck gives up. These are options, not requirements. Every proposed swap must name both the cut and the add. If there is no concrete cut, list the card under flex/bench considerations instead of calling it a swap.>

## What Changed vs. Previous Pass
<bullet list of OUT → IN swaps with reasons; omit on first pass>

## Mana Base
<dual lands, utility, fetches, basics; color-source summary>

## Owned but Not in Deck (flex slots)
<table of EDHREC top-N picks the user owns but deliberately left out>

## Wishlist (future rare/mythic targets)
<ranked list of unowned high-lift cards that need rare/mythic wildcards; cite lift as `N.Nx` (never as synergy %) with inclusion>

## Questions for You
<preferences that would change a recommendation, e.g. a favourite card or speed vs. value; omit if none>

## Summary
<one paragraph: where the deck stands and the main options, + path to decklist file>
```
