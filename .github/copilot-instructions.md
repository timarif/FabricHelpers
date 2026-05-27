# Copilot instructions for FabricHelpers

This file is the short, always-on system prompt that Copilot reads on every
prompt in this repo. The full agent contract lives in [`AGENTS.md`](../AGENTS.md);
the contributor guide lives in [`CONTRIBUTING.md`](../CONTRIBUTING.md).

## Repo shape

Monorepo with five helpers; the four wheels share `fabric-core`:

```
coreHelper/         → fabric-core         (shared low-level)
scannerHelper/      → fabric-scanner       depends on fabric-core
downloaderHelper/   → fabric-downloader    depends on fabric-core
splitterHelper/     → fabric-splitter      depends on fabric-core
mpeHelper/          → notebook + Terraform (not a wheel)
reportingHelper/    → notebook (not a wheel)
```

## Non-negotiables

1. **`fabric-core` MUST NOT import from any consumer wheel.** The three
   consumers MUST NOT import each other. AST tests enforce this in CI.
2. If you find yourself copy-pasting between consumers, move the shared
   code into `fabric-core` behind a small interface instead.
3. When mocking core helpers in consumer tests, patch
   `fabric_core.auth.X` — not the consumer's re-export of `X`.
4. When a consumer starts using a new `fabric-core` API, bump that
   consumer's `pyproject.toml` lower bound to match.
5. After touching a notebook cell template, run the package's
   `python scripts/build_notebook.py` and commit the regenerated
   `notebooks/*.ipynb`. CI fails if these are out of sync.
6. Never edit `_version.py` or `[project] version` by hand — releases
   bump these via `.github/workflows/main.yml`.

## House style

- Python 3.10+; `from __future__ import annotations` everywhere.
- Frozen dataclasses for config; validate in `__post_init__`.
- Lazy imports for `pyspark`, `notebookutils`, `aiohttp` — engine half
  must import on a vanilla Python install.
- `logging.getLogger(__name__)` — no `print(...)` in library code.
- Tests live in `tests/unit/`; run with `pytest tests/unit -q` per package.
- No new top-level deps without explicit approval in the issue.

## Quick test commands

```bash
# Install everything editable in dependency order
cd coreHelper       && pip install -e ".[dev,api,notebook]" && cd ..
cd scannerHelper    && pip install -e ".[dev,api,spark]"    && cd ..
cd downloaderHelper && pip install -e ".[dev,api,spark]"    && cd ..
cd splitterHelper   && pip install -e ".[dev]"              && cd ..

# Run all four wheel test suites
for pkg in coreHelper scannerHelper downloaderHelper splitterHelper; do
  (cd "$pkg" && pytest tests/unit -q) || exit 1
done
```

See `AGENTS.md` for the full issue-to-PR contract.
