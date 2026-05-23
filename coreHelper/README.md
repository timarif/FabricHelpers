# fabric-core

Shared low-level helpers for the [FabricHelpers](https://github.com/timarif/FabricHelpers)
monorepo. Both [`fabric-scanner`](../scannerHelper) and
[`fabric-downloader`](../downloaderHelper) depend on this wheel so they
share a single bug-fix surface for auth, REST, path math, diagnostics, and
notebook-build plumbing.

## Install

```pwsh
%pip install fabric-core
```

For development:

```pwsh
cd coreHelper
pip install -e ".[dev,api,notebook]"
pytest tests/unit/
```

## Public API

| Module | What it owns |
|---|---|
| `fabric_core.auth` | `TokenError`, `get_token(audience, *, force_refresh=False)`, `_from_notebookutils`, `_from_mssparkutils`, `_from_env`, `_from_azure_cli`, `_from_default_credential`. Five-source chain. Callers **must supply `audience` explicitly** — no default. |
| `fabric_core.paths` | `ONELAKE_HOST`, `table_path`, `files_path`, `files_uri`, `fs_ls`, `_import_nbu`, `detect_notebook_runtime`. Pure path math + `notebookutils` shim. |
| `fabric_core.enumerate` | `enumerate_workspaces_items(*, token, pbi_base, fabric_base, timeout, workspace_concurrency, item_filter=None, log=None)`, `run_enumeration_sync(**kw)`, plus module-private `_http_json` and `_list_*_workspaces` helpers. |
| `fabric_core.diagnostics` | `ProbeResult` dataclass, `probe_api(*, token, pbi_base, fabric_base, timeout=30.0) -> list[ProbeResult]`. Synchronous four-endpoint probe. |
| `fabric_core.build_notebook` | `NotebookBuildSpec` dataclass, `write_notebook(spec) -> Path`, `_md`, `_code`, `_slug`, `_load_version`. Library-form of the per-package `scripts/build_notebook.py`. |

## Design

`fabric-core` is meant to be **boring**: zero opinions about output schemas, no
Spark dependency, no I/O beyond what the wrapped subsystem already does.
Anything product-specific (the scanner's `ResolvedPaths`, the downloader's
`build_paths`, schemas, persist logic, configs) stays in the consuming wheel.

## Tests

~76 unit tests in `tests/unit/` cover the token chain (15), path math (20),
workspace enumeration with mocked aiohttp via `aioresponses` (15),
the four-endpoint probe (11), and the notebook-build library (15).

## License

MIT. See [LICENSE](../LICENSE).
