"""User-facing configuration for the Fabric item downloader.

`DownloaderConfig` is a frozen dataclass — every knob lives here and the rest
of the package threads it through unchanged. Defaults reproduce the seed
notebook (`notebook_downloader.ipynb`) for a single-type Notebook download
with the additional ability to opt into multi-type downloads (Notebook +
DataPipeline + Dataflow + anything else `getDefinition` supports) via the
`item_types` tuple.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Mapping


# Built-in item types known to expose `POST /items/{id}/getDefinition`.
# This is informational only — the enumerate/fetch layers accept any string
# the caller drops into `item_types`. New Fabric item types can be added by
# users without a package release.
KNOWN_ITEM_TYPES: tuple[str, ...] = (
    "Notebook",
    "DataPipeline",
    "Dataflow",
    "Report",
    "SemanticModel",
    "SparkJobDefinition",
)


# Per-type format hints for **non-Notebook** types. When a type appears as a
# key, its value is passed as the `?format=` query string to `getDefinition`.
# When missing, the call uses the default (no format) which returns every
# part separately ("parts" mode). Notebook downloads are controlled by the
# dedicated `notebook_format` knob — passing `"Notebook"` here raises.
DEFAULT_FORMAT_BY_TYPE: Mapping[str, str] = {}


# Valid values for `DownloaderConfig.notebook_format`. The Fabric
# `getDefinition` endpoint advertises `ipynb` and `fabricGitSource`; we map
# those (plus a raw "parts" pass-through and a single-file "txt") onto
# user-facing names:
#   - "py"    : native source mode (no `?format=` hint; API returns
#               `notebook-content.<lang>` + `.platform`). We extract the
#               source part and save it as a single file with the
#               language-specific extension (`.py`, `.scala`, `.sql`, `.r`).
#   - "txt"   : same fetch as "py" but the source is saved as a single
#               `.txt` file regardless of language. Useful for systems
#               that index notebooks as plain text.
#   - "ipynb" : sends `?format=ipynb`; saves the single `.ipynb` part.
#   - "parts" : no `?format=` hint; writes every part as a separate `.txt`
#               file (same shape as non-notebook item types).
NOTEBOOK_FORMATS: tuple[str, ...] = ("py", "txt", "ipynb", "parts")


@dataclass(frozen=True)
class DownloaderConfig:
    # --- What to download ---------------------------------------------------
    item_types: tuple[str, ...] = ("Notebook",)
    """Fabric item types to enumerate + download (`Notebook`, `DataPipeline`,
    `Dataflow`, etc.). The enumerate/fetch layers accept any Fabric item
    type string supported by /v1/admin/items + /getDefinition."""

    format_by_type: Mapping[str, str] = field(
        default_factory=lambda: dict(DEFAULT_FORMAT_BY_TYPE))
    """Per-type `?format=` overrides for **non-Notebook** types. Missing keys
    -> no format param (the API returns every definition part separately =
    "parts" mode). The legacy `"Notebook"` key is rejected at validation
    time — use `notebook_format` instead."""

    notebook_format: str = "py"
    """How to download Fabric Notebook items. One of:

    - ``"py"`` *(default)*: save the notebook's native source as a single
      file ``<name>__<id>.<ext>`` where ``<ext>`` matches the notebook
      language (``.py`` for PySpark/Python, ``.scala`` / ``.sql`` / ``.r``
      for non-Python). Calls the API without a `?format=` hint (Fabric
      defaults to ``fabricGitSource``).
    - ``"txt"``: same fetch as ``"py"`` but the source is written as a
      single ``<name>__<id>.txt`` regardless of language. Handy when a
      downstream system expects plain-text files.
    - ``"ipynb"``: save as a single self-contained ``<name>__<id>.ipynb``
      Jupyter file. Calls the API with ``?format=ipynb``.
    - ``"parts"``: write every part of the definition envelope as a
      separate ``.txt`` file (same shape as non-notebook types). Calls the
      API without a `?format=` hint.

    Non-notebook item types are unaffected by this setting; use
    `format_by_type` for per-type `?format=` overrides on those."""

    # --- Enumeration --------------------------------------------------------
    admin_mode: bool = True
    """When True, try tenant-admin endpoints first (PBI admin/groups ->
    Fabric admin/workspaces -> user /workspaces). When False, only the
    user-scoped `/v1/workspaces` endpoint is used."""

    read_workspace_ids: tuple[str, ...] = field(default_factory=tuple)
    """Allowlist filter. Empty tuple = all visible workspaces."""

    max_items: int = 0
    """Hard cap on items fetched per run. 0 disables the cap. Useful for
    dry-runs (e.g. `max_items=5`)."""

    # --- Output -------------------------------------------------------------
    output_root: str = "fabric_item_backups"
    """Sub-folder under `Files/` where the downloaded files land."""

    run_label: str = ""
    """Identifies this run in the manifest table. Empty -> auto-generated
    as `yyyy-mm-dd_HH-MM-SS` UTC at runtime."""

    manifest_table: str = "fabric_download_manifest"
    """Delta table that records one row per download attempt."""

    include_raw_definition: bool = False
    """Also save the raw getDefinition JSON envelope (full body with
    platform metadata) as `<name>__<id>.item.json` — useful for
    round-trip restore."""

    skip_existing: bool = True
    """Skip writing files whose target path already exists. Lets you
    safely resume a partial run by re-running with the same `run_label`."""

    group_by_type: bool = True
    """Group output folders by item type: `<wsName>__<wsId>/<Type>/<file>`.
    Set False to flatten everything under `<wsName>__<wsId>/<file>` (the
    seed notebook's layout — only safe when `item_types` is a single
    type)."""

    # --- Write target -------------------------------------------------------
    write_to_default_lakehouse: bool = True
    write_workspace_id: str = ""
    write_lakehouse_id: str = ""
    write_schema: str | None = None

    # --- Fabric REST --------------------------------------------------------
    fabric_base:    str = "https://api.fabric.microsoft.com"
    pbi_base:       str = "https://api.powerbi.com"
    token_audience: str = "pbi"
    """Audience string passed to `notebookutils.credentials.getToken`.
    Both `"pbi"` and `"https://api.fabric.microsoft.com"` work in the
    Fabric runtime; `"pbi"` is the seed notebook's default."""

    # --- Spark distribution -------------------------------------------------
    num_partitions: int = 0
    """0 -> use `sc.defaultParallelism`."""

    executor_concurrency: int = 30
    """Async in-flight fetches per Spark partition."""

    max_retries: int = 4
    """Per-item retries before giving up (covers 401/429/5xx)."""

    # ----------------------------------------------------------------------
    def __post_init__(self) -> None:
        if not self.item_types:
            raise ValueError("item_types must contain at least one type")
        if not all(isinstance(t, str) and t for t in self.item_types):
            raise ValueError("item_types entries must be non-empty strings")
        if not self.output_root:
            raise ValueError("output_root must be non-empty")
        if self.executor_concurrency < 1:
            raise ValueError("executor_concurrency must be >= 1")
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if self.num_partitions < 0:
            raise ValueError("num_partitions must be >= 0")
        if self.max_items < 0:
            raise ValueError("max_items must be >= 0")
        if (not self.write_to_default_lakehouse
                and not (self.write_workspace_id and self.write_lakehouse_id)):
            raise ValueError(
                "write_to_default_lakehouse=False requires both "
                "write_workspace_id and write_lakehouse_id")
        if self.notebook_format not in NOTEBOOK_FORMATS:
            raise ValueError(
                f"notebook_format must be one of {NOTEBOOK_FORMATS!r}; "
                f"got {self.notebook_format!r}")
        if "Notebook" in dict(self.format_by_type or {}):
            raise ValueError(
                "format_by_type['Notebook'] is no longer supported. "
                "Use notebook_format='py' | 'ipynb' | 'parts' instead. "
                "(Previous default 'ipynb' is now notebook_format='ipynb'; "
                "the new default 'py' downloads notebooks as native "
                "source files.)")

    # ----------------------------------------------------------------------
    @classmethod
    def from_dict(cls, d: dict) -> "DownloaderConfig":
        """Build a config from a plain dict (e.g. JSON-loaded notebook
        params). Unknown keys raise TypeError so typos show up loudly."""
        valid = {f.name for f in fields(cls)}
        unknown = set(d) - valid
        if unknown:
            raise TypeError(
                f"Unknown DownloaderConfig fields: {sorted(unknown)}")
        # Cast list values back to tuple for the tuple-typed fields.
        d = dict(d)
        for tuple_field in ("item_types", "read_workspace_ids"):
            if tuple_field in d and not isinstance(d[tuple_field], tuple):
                d[tuple_field] = tuple(d[tuple_field])
        return cls(**d)

    def to_dict(self) -> dict:
        out: dict = {}
        for f in fields(self):
            v = getattr(self, f.name)
            if isinstance(v, tuple):
                out[f.name] = list(v)
            elif isinstance(v, Mapping):
                out[f.name] = dict(v)
            else:
                out[f.name] = v
        return out

    def format_for(self, item_type: str) -> str | None:
        """Return the `?format=` value for `item_type`, or None when no
        override is configured (defaults to parts mode).

        Notebook items consult ``notebook_format``: only ``"ipynb"`` mode
        sends a hint (`?format=ipynb`). All other modes (`"py"`, `"txt"`,
        `"parts"`) omit the hint so the API returns the native source +
        `.platform` parts (Fabric's `fabricGitSource` default)."""
        if item_type == "Notebook":
            return "ipynb" if self.notebook_format == "ipynb" else None
        return self.format_by_type.get(item_type) if self.format_by_type else None

    def export_mode_for(self, item_type: str) -> str:
        """Internal writer mode. For Notebook returns ``notebook_format``
        directly (`"py"` | `"ipynb"` | `"parts"`). For other types,
        ``"ipynb"`` when this type has an `?format=ipynb` override, else
        ``"parts"``."""
        if item_type == "Notebook":
            return self.notebook_format
        fmt = self.format_by_type.get(item_type) if self.format_by_type else None
        return "ipynb" if fmt == "ipynb" else "parts"
