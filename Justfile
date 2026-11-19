# `just` with no arguments lists recipes instead of running the first one.
set default-list

# Project-local uv cache, exported to every recipe so they also work in the agent sandbox
# (where ~/.cache/uv is read-only).
export UV_CACHE_DIR := ".cache/uv"

# Upgrade all locked dependencies and sync the environment.
update-deps:
    uv lock --upgrade
    uv sync

# Run ManaScope; arguments are forwarded with their quoting intact.
[positional-arguments]
manascope *args:
    @uv run manascope "$@"

# Lint, format check, type check, and tests.
check:
    uv run ruff check src/ tests/
    uv run ruff format --check src/ tests/
    uv run ty check src/
    uv run python -m pytest tests/

# Slow ReDoS regression tests.
test-slow:
    uv run python -m pytest tests/ -m slow
