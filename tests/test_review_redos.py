"""ReDoS smoke tests for review.SLUG_PATTERNS / _FALLBACK_THEMES.

The theme regexes use bounded .{m,n} spans but are fed untrusted Scryfall
oracle text. This file runs each compiled pattern against adversarial
strings (long runs of nothing, alternating chars, near-match prefixes)
in a child process with a hard timeout and asserts every match finishes
under a generous budget.

Running in a child process is deliberate: Python's re engine holds the
GIL during a match, so a thread-based timeout cannot interrupt a
catastrophic backtrack. If a pattern regresses, the child is terminated
and the test fails cleanly instead of hanging pytest.
"""

from __future__ import annotations

import multiprocessing as mp
import re

import pytest

from manascope.review import _FALLBACK_THEMES, SLUG_PATTERNS

# Budget is generous because Windows CI can be slow; true ReDoS blows
# through seconds/minutes, so even 1.0 s is a strong signal. Process
# startup on Windows (spawn) eats a few hundred ms, so don't go lower.
BUDGET_S = 1.0


def _collect_patterns() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for slug, (type_pat, text_pat) in SLUG_PATTERNS.items():
        if type_pat:
            out.append((f"slug:{slug}:type", type_pat))
        if text_pat:
            out.append((f"slug:{slug}:text", text_pat))
    for name, type_pat, text_pat in _FALLBACK_THEMES:
        if type_pat:
            out.append((f"fallback:{name}:type", type_pat))
        if text_pat:
            out.append((f"fallback:{name}:text", text_pat))
    return out


PATTERNS = _collect_patterns()

# Adversarial inputs: long runs that look like they could fan out the
# bounded .{m,n} spans without actually matching.
ADVERSARIAL_INPUTS = [
    "a" * 5000,
    "return " + "x" * 5000,
    "exile " + "x" * 5000 + " battlefield",
    "when " + "x" * 5000 + " enters",
    "create a " + "x" * 5000 + " token",
    "cast " + "x" * 5000,
    "deals 1 damage to " + "x" * 5000,
]


def _run_pattern(pattern: str, inputs: list[str]) -> None:
    """Compile and search each input once. Executed in a child process."""
    compiled = re.compile(pattern, re.IGNORECASE)
    for text in inputs:
        compiled.search(text)


@pytest.mark.slow
@pytest.mark.parametrize(("name", "pattern"), PATTERNS)
def test_pattern_under_budget(name: str, pattern: str) -> None:
    ctx = mp.get_context("spawn")
    proc = ctx.Process(target=_run_pattern, args=(pattern, ADVERSARIAL_INPUTS))
    proc.start()
    proc.join(BUDGET_S)
    if proc.is_alive():
        proc.terminate()
        proc.join(1.0)
        if proc.is_alive():
            proc.kill()
            proc.join(1.0)
        pytest.fail(
            f"{name} exceeded {BUDGET_S}s on adversarial input (likely catastrophic backtracking)"
        )
    assert proc.exitcode == 0, f"{name} child exited with code {proc.exitcode}"
