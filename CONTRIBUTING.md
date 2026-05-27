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

## Proposing a change (fork-based workflow)

External contributors **must work from a fork** — only repository
maintainers can push directly to `timarif/FabricHelpers`. This keeps the
release pipeline on `main` predictable and lets every change be reviewed.

### 1. Fork the repository

Click **Fork** in the top-right of <https://github.com/timarif/FabricHelpers>,
or via the GitHub CLI:

```bash
gh repo fork timarif/FabricHelpers --clone --remote
cd FabricHelpers
```

`--remote` configures two remotes for you:

- `origin` → your fork (where you push branches)
- `upstream` → `timarif/FabricHelpers` (where you pull updates from)

If you cloned manually instead, wire it up by hand:

```bash
git clone https://github.com/<your-username>/FabricHelpers.git
cd FabricHelpers
git remote add upstream https://github.com/timarif/FabricHelpers.git
```

### 2. Create a feature branch off an up-to-date `main`

Never commit directly to your fork's `main` — keep it as a clean mirror
of upstream so it's easy to rebase and so PRs are diffed cleanly.

```bash
git fetch upstream
git switch main
git rebase upstream/main
git push origin main           # keep your fork's main in sync

git switch -c <scope>/<short-description>
```

Branch name convention: `<scope>/<kebab-case-description>`, where `<scope>`
is one of `core`, `scanner`, `downloader`, `splitter`, `mpe`, `reporting`,
`repo`, `ci`, `docs`. Examples:

- `scanner/handle-404-from-admin-items`
- `core/add-onelake-uri-helper`
- `ci/cache-pip-by-pyproject`

### 3. Make your change, then test the package(s) you touched

Install dependencies once (see [Local development](#local-development)
below), then run the **unit suite for every package your change affects**:

```bash
cd <pkg>Helper && pytest tests/unit -q
```

If you touched `fabric-core`, run all four downstream suites — the change
must not break any consumer. CI will block the PR otherwise.

If you touched a notebook cell template (`<pkg>Helper/scripts/build_notebook.py`),
regenerate the bound notebook and commit the result:

```bash
cd <pkg>Helper && python scripts/build_notebook.py
git add notebooks/
```

### 4. Push to your fork and open a pull request

```bash
git push -u origin <scope>/<short-description>
gh pr create \
    --repo timarif/FabricHelpers \
    --base main \
    --head <your-username>:<scope>/<short-description> \
    --title "<scope>: <short description> (closes #<issue>)" \
    --body  "Closes #<issue>. <one-paragraph summary + what you ran.>"
```

PR requirements:

- **One concern per PR.** Refactors that aren't required by the issue go
  in a follow-up PR.
- **Link the issue with `Closes #N`** in the PR body. This auto-closes
  the issue when the PR merges.
- **Include a "what I ran / what passed" block** in the PR body. At
  minimum: `pytest tests/unit -q` for every package you touched.
- **No bumps to `_version.py` or `[project] version`** — releases handle
  those (see [Tag and release scheme](#tag-and-release-scheme)).
- **No new top-level dependencies** without prior agreement in the issue.

### 5. Iterate on review feedback

```bash
# work on the same branch, push fixups
git commit --fixup HEAD
git push origin <scope>/<short-description>

# when review is done, rebase + squash before merging
git rebase -i --autosquash upstream/main
git push --force-with-lease origin <scope>/<short-description>
```

Use **"Squash and merge"** in the PR UI so each PR lands as one commit
on `main` — this keeps the path-filtered release detection
(`.github/workflows/main.yml`) clean.

### 6. After merge: delete the branch, sync your fork

```bash
gh pr close <pr-number> --delete-branch    # if not auto-deleted
git switch main
git fetch upstream
git rebase upstream/main
git push origin main
```

> **Maintainers note**: a small number of repository maintainers can
> push directly to `main` (e.g. release-pipeline housekeeping, doc
> typos). When you do, include `[skip release]` in the commit message
> if the change doesn't touch any package under `*Helper/` — it short-
> circuits the release detection job in `main.yml`.

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
