# Contributing to FabricHelpers

This monorepo ships **four independent wheels** that move together:

```
              ┌──────────────────┐
              │   fabric-core    │   shared low-level helpers
              │  (coreHelper/)   │   auth · paths · enumerate · diagnostics · build_notebook
              └────────┬─────────┘
                       │   imported by
        ┌──────────────┼──────────────────┐
        ▼              ▼                  ▼
┌──────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
│  fabric-scanner  │  │  fabric-downloader   │  │  fabric-splitter     │
│ (scannerHelper/) │  │ (downloaderHelper/)  │  │ (splitterHelper/)    │
└──────────────────┘  └──────────────────────┘  └──────────────────────┘
```

`fabric-scanner`, `fabric-downloader`, and `fabric-splitter` all depend on
`fabric-core>=0.1,<1.0`. They never import each other.

---

## Dependency direction (enforced by tests)

- `fabric-core` MUST NOT import from `fabric-scanner`, `fabric-downloader`, or `fabric-splitter`.
- `fabric-scanner` MUST NOT import from `fabric-downloader` or `fabric-splitter` (and vice versa).
- `fabric-splitter` MUST NOT import from `fabric-scanner` or `fabric-downloader`.

Each package ships an AST-walking test (`tests/unit/test_no_cross_imports.py`)
that fails CI if these rules are broken.

---

## When to add code to `fabric-core` vs. a consumer

| Goes in `fabric-core` | Stays in the consumer |
|---|---|
| Token acquisition (any audience) | Scanner-specific config dataclasses |
| OneLake / Fabric REST URL math | Spark schemas (`StructType`) |
| Workspace + item enumeration (with a filter callback) | Persist / SQL rollup logic |
| Endpoint-probe diagnostics | Output-path builders (`ResolvedPaths`, `build_paths`) |
| Notebook-build serialization | The per-package `scripts/build_notebook.py` cell template |

If you find yourself copy-pasting code from one consumer to the other, that's
a strong signal it should move to `fabric-core` behind a small interface.

---

## Adopting a new `fabric-core` API in a consumer

When a consumer starts using a function added in `fabric-core` X.Y.Z, **bump
the consumer's lower bound to match**:

```toml
# scannerHelper/pyproject.toml
dependencies = [
    "fabric-core>=0.1.1,<1.0",   # ← bumped from 0.1
    ...
]
```

This prevents `pip install fabric-scanner` from resolving to an older
`fabric-core` that doesn't have the new API.

The upper bound stays `<1.0` until we cut a real breaking-change `1.0`.

---

## Mock-patching gotcha

Consumer `auth.py` re-exports symbols from `fabric_core.auth` for back-compat:

```python
# scannerHelper/src/fabric_scanner/api/auth.py
from fabric_core.auth import TokenError, _from_env, _from_notebookutils  # noqa: F401
from fabric_core.auth import get_token as _core_get_token

def get_token(audience="https://api.fabric.microsoft.com", **kw):
    return _core_get_token(audience=audience, **kw)
```

When you write a test that needs to patch one of those helpers, you **must
patch it in `fabric_core.auth`, not in the consumer**:

```python
# ❌ NO — patches a name the consumer re-exports but doesn't call.
with mock.patch("fabric_scanner.api.auth._from_env", return_value=("tok", 0)):
    ...

# ✅ YES — patches the name that get_token actually resolves at call time.
with mock.patch("fabric_core.auth._from_env", return_value=("tok", 0)):
    ...
```

`fabric_core.auth.get_token` resolves `_from_env` in its own module's
namespace; patching the re-exported name in the consumer is a no-op.

---

## Tag and release scheme

| Package | Tag prefix | Example |
|---|---|---|
| `fabric-core` | `core-v` | `core-v0.1.0` |
| `fabric-scanner` | `v` (legacy, BC) or `scanner-v` | `v0.3.4`, `scanner-v0.4.0` |
| `fabric-downloader` | `downloader-v` | `downloader-v0.1.0` |
| `fabric-splitter` | `splitter-v` | `splitter-v0.1.0` |

Releases are driven by `.github/workflows/main.yml`. On every push to `main`:

1. The `detect` job decides which package directories changed.
2. For each changed package, `release-package.yml` (a reusable workflow):
   bumps `_version.py`, commits and tags, builds the wheel, smoke-tests it,
   then pauses for **manual approval** (`environment: production`).
3. After approval, the same job publishes a GitHub Release **and** uploads to
   PyPI via OIDC Trusted Publishing.

`fabric-core` releases first, then the orchestrator waits for the new version
to appear on the PyPI index before kicking off the scanner / downloader
release jobs, so their builds resolve against the just-published core.

To opt out of releasing for a single commit, include `[skip release]` in the
commit message of the merge to `main`.

To re-run a release for an existing tag (e.g. failed artifact upload), use
the manual `release.yml` workflow with `package` + `tag` inputs.

---

## One-time GitHub UI setup (already done; documented for repo forks)

1. **Settings → Actions → General → Workflow permissions** → **Read and write
   permissions**. Lets the bump job push to `main`.
2. **Settings → Environments** → create `production` with a required reviewer.
   The release/PyPI publish step waits on approval here.
3. **PyPI Trusted Publishing**: at
   <https://pypi.org/manage/account/publishing/> add an entry for each
   package: owner `timarif`, repository `FabricHelpers`, workflow
   `release-package.yml`, environment `production`.

---

## Local development

```pwsh
# Install all four packages editable, in dependency order.
cd coreHelper       ; pip install -e ".[dev,api,notebook]" ; cd ..
cd scannerHelper    ; pip install -e ".[dev,api,spark]"    ; cd ..
cd downloaderHelper ; pip install -e ".[dev,api,spark]"    ; cd ..
cd splitterHelper   ; pip install -e ".[dev]"              ; cd ..

# Run all four test suites.
cd coreHelper       ; pytest tests/unit -q ; cd ..
cd scannerHelper    ; pytest tests/unit -q ; cd ..
cd downloaderHelper ; pytest tests/unit -q ; cd ..
cd splitterHelper   ; pytest tests/unit -q ; cd ..

# Run the release helper unit tests.
pytest tests/test_release_package.py -q
```

When you touch a notebook cell template, regenerate the notebooks and commit
the result:

```pwsh
cd scannerHelper    ; python scripts/build_notebook.py        ; cd ..
cd downloaderHelper ; python scripts/build_notebook.py        ; cd ..
```

Notebook cell IDs are derived from a SHA-1 of the cell source, so re-running
`build_notebook.py` against an unchanged template produces byte-identical
output (CI verifies this).
