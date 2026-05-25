"""Command-line interface for fabric-downloader.

Provides a ``fabric-downloader`` entry-point that wraps the Spark-free
engine path — suitable for laptops, CI pipelines, or any environment
where PySpark is not available.  Authentication falls back to environment
variables (``FABRIC_TOKEN``) or Azure CLI / DefaultAzureCredential.

Usage examples::

    fabric-downloader \\
        --workspace-id  <uuid> \\
        --output        ./downloads \\
        --item-types    Notebook,DataPipeline,Report \\
        --notebook-format py

    fabric-downloader \\
        --workspace-id  <uuid> \\
        --exclude-item-types Lakehouse \\
        --token         $MY_TOKEN
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import KNOWN_ITEM_TYPES, DownloaderConfig
from .item_types import REGISTRY
from .api.enumerate import run_enumeration_sync

# Ensure all built-in handlers are registered before the CLI runs.
import fabric_downloader.handlers  # noqa: F401

log = logging.getLogger(__name__)

_ALL_SENTINEL = "all"

# Item types whose ``getDefinition`` endpoint is not available (or not
# useful) — skip the fetch step and let the handler produce its own output
# from the item metadata alone.
_METADATA_ONLY_TYPES = {"Lakehouse"}


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fabric-downloader",
        description=(
            "Download Fabric item definitions from one workspace to disk. "
            "Authentication uses FABRIC_TOKEN env-var, Azure CLI, or "
            "DefaultAzureCredential."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Required
    parser.add_argument(
        "--workspace-id",
        required=True,
        metavar="UUID",
        help="Fabric workspace ID to download from.",
    )

    # Output
    parser.add_argument(
        "--output",
        default="fabric_downloads",
        metavar="DIR",
        help="Root output directory.  Default: %(default)r.",
    )
    parser.add_argument(
        "--run-label",
        default="",
        metavar="LABEL",
        help=(
            "Label for this run (used as a sub-folder name).  "
            "Defaults to a UTC timestamp."
        ),
    )

    # Type selection
    known_lower = ", ".join(sorted(t.lower() for t in KNOWN_ITEM_TYPES))
    parser.add_argument(
        "--item-types",
        default=_ALL_SENTINEL,
        metavar="TYPES",
        help=(
            "Comma-separated Fabric item types to download, or 'all' to "
            f"download every type registered in the handler registry.  "
            f"Known types: {known_lower}.  Default: %(default)r."
        ),
    )
    parser.add_argument(
        "--exclude-item-types",
        default="",
        metavar="TYPES",
        help=(
            "Comma-separated item types to exclude.  Applied after "
            "--item-types.  Example: --exclude-item-types Lakehouse."
        ),
    )

    # Notebook-specific
    parser.add_argument(
        "--notebook-format",
        default="py",
        choices=("py", "txt", "ipynb", "parts"),
        help=(
            "Format for Notebook items.  Ignored for other types.  "
            "Default: %(default)r."
        ),
    )

    # Auth
    parser.add_argument(
        "--token",
        default="",
        metavar="BEARER",
        help=(
            "Pre-fetched bearer token.  When omitted the CLI tries "
            "FABRIC_TOKEN env-var then Azure CLI / DefaultAzureCredential."
        ),
    )
    parser.add_argument(
        "--token-audience",
        default="pbi",
        metavar="AUDIENCE",
        help="Token audience.  Default: %(default)r.",
    )

    # Behaviour knobs
    parser.add_argument(
        "--admin-mode",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Try Fabric admin APIs first (default).  Pass --no-admin-mode "
            "to use only user-scoped APIs."
        ),
    )
    parser.add_argument(
        "--skip-existing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip writing files that already exist (default: enabled).",
    )
    parser.add_argument(
        "--include-raw-definition",
        action="store_true",
        default=False,
        help=(
            "Also save the raw getDefinition JSON envelope as "
            "<name>__<id>.item.json alongside each item."
        ),
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=0,
        metavar="N",
        help="Hard cap on items downloaded.  0 = unlimited.  Default: %(default)s.",
    )
    parser.add_argument(
        "--manifest",
        default="",
        metavar="FILE",
        help=(
            "Path to write the JSON manifest file.  "
            "Defaults to <output>/<run_label>/_manifest.json."
        ),
    )

    # Verbosity
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=False,
        help="Enable DEBUG-level logging.",
    )

    return parser


def resolve_item_types(
    item_types_arg: str,
    exclude_arg: str,
) -> tuple[str, ...]:
    """Compute the final item_types tuple from CLI arguments.

    Parameters
    ----------
    item_types_arg:
        Raw ``--item-types`` value, e.g. ``"all"`` or
        ``"Notebook,DataPipeline"``.
    exclude_arg:
        Raw ``--exclude-item-types`` value, e.g. ``"Lakehouse"``.

    Returns
    -------
    tuple[str, ...]
        Non-empty tuple of Fabric item type strings, original-case as
        supplied (or as registered in the handler registry for ``"all"``).
    """
    if item_types_arg.strip().lower() == _ALL_SENTINEL:
        # Use everything registered (preserves original-case from handler).
        candidates = [cls.item_type for cls in REGISTRY.values()]
    else:
        candidates = [t.strip() for t in item_types_arg.split(",") if t.strip()]

    if exclude_arg:
        excluded = {t.strip().lower() for t in exclude_arg.split(",") if t.strip()}
        candidates = [t for t in candidates if t.lower() not in excluded]

    if not candidates:
        raise ValueError(
            "No item types remain after applying --item-types and "
            "--exclude-item-types.  Check your arguments."
        )
    return tuple(candidates)


# ---------------------------------------------------------------------------
# Token acquisition
# ---------------------------------------------------------------------------


def _acquire_token(args: argparse.Namespace) -> str:
    """Return a bearer token: explicit flag > env var > SDK chain."""
    if args.token:
        return args.token
    env_token = os.environ.get("FABRIC_TOKEN", "")
    if env_token:
        return env_token
    from .api.auth import TokenError, get_token
    try:
        return get_token(args.token_audience)
    except TokenError as exc:
        log.error("Could not acquire token: %s", exc)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Download helpers (Spark-free engine path)
# ---------------------------------------------------------------------------


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fetch_definition_sync(
    workspace_id: str,
    item_id: str,
    token: str,
    fabric_base: str,
    format_hint: str | None,
) -> dict | None:
    """Synchronous single-item getDefinition call (no Spark, no aiohttp)."""
    import urllib.error
    import urllib.request

    suffix = f"?format={format_hint}" if format_hint else ""
    url = (f"{fabric_base}/v1/workspaces/{workspace_id}/items/{item_id}"
           f"/getDefinition{suffix}")
    req = urllib.request.Request(
        url,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        data=b"",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        log.warning("getDefinition HTTP %d for item %s: %s",
                    exc.code, item_id, exc.reason)
        return None
    except Exception as exc:
        log.warning("getDefinition error for item %s: %s", item_id, exc)
        return None


def _write_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _safe_seg(s: str, maxlen: int = 80) -> str:
    import re
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", str(s or ""))
    safe = safe.strip("._-") or "unnamed"
    return safe[:maxlen]


# ---------------------------------------------------------------------------
# Main download loop
# ---------------------------------------------------------------------------


def download_items(
    args: argparse.Namespace,
    item_types: tuple[str, ...],
    token: str,
) -> list[dict]:
    """Enumerate + download items; return manifest rows."""
    fabric_base = "https://api.fabric.microsoft.com"
    cfg = DownloaderConfig(
        item_types=item_types,
        notebook_format=args.notebook_format,
        admin_mode=args.admin_mode,
        read_workspace_ids=(args.workspace_id,),
        max_items=args.max_items,
        output_root=args.output,
        run_label=args.run_label,
        skip_existing=args.skip_existing,
        include_raw_definition=args.include_raw_definition,
        token_audience=args.token_audience,
        write_to_default_lakehouse=False,
        # Dummy IDs — this CLI path never writes to a Lakehouse.
        write_workspace_id="_cli",
        write_lakehouse_id="_cli",
    )

    log.info("Enumerating items in workspace %s ...", args.workspace_id)
    items = run_enumeration_sync(cfg, token)
    log.info("Found %d items matching %s.", len(items), list(item_types))
    if cfg.max_items:
        items = items[: cfg.max_items]

    run_label = cfg.run_label or _auto_run_label()
    output_root = Path(args.output).resolve()
    manifest_rows: list[dict] = []

    for item in items:
        row = _download_one(
            item=item,
            token=token,
            fabric_base=fabric_base,
            notebook_format=args.notebook_format,
            skip_existing=args.skip_existing,
            include_raw=args.include_raw_definition,
            output_root=output_root,
            run_label=run_label,
        )
        manifest_rows.append(row)
        status = row["status"]
        log.info(
            "[%s] %s/%s  %s",
            status, row["item_type"], row["display_name"], row.get("error") or "",
        )

    return manifest_rows


def _auto_run_label() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")


def _download_one(
    *,
    item: dict,
    token: str,
    fabric_base: str,
    notebook_format: str,
    skip_existing: bool,
    include_raw: bool,
    output_root: Path,
    run_label: str,
) -> dict:
    """Download a single item; return a manifest row dict."""
    item_type  = item.get("type", "")
    item_id    = item.get("id", "")
    ws_id      = item.get("workspaceId", "")
    ws_name    = item.get("workspaceName") or ws_id or "unknown_ws"
    disp_name  = item.get("displayName") or item.get("name") or item_id
    now        = datetime.now(timezone.utc).isoformat()

    base_row: dict = {
        "downloaded_at": now,
        "run_label":     run_label,
        "workspace_id":  ws_id,
        "workspace_name": ws_name,
        "item_type":     item_type,
        "item_id":       item_id,
        "display_name":  disp_name,
        "endpoint":      (f"{fabric_base}/v1/workspaces/{ws_id}"
                          f"/items/{item_id}/getDefinition"),
        "sha256":        None,
        "bytes":         None,
        "status":        "error",
        "error":         None,
    }

    handler_cls = REGISTRY.get(item_type.lower())

    # Build the output folder: <output>/<run_label>/<ws>/<type>/<name>__<id8>
    safe_ws   = _safe_seg(ws_name or ws_id or "unknown")
    safe_type = _safe_seg(item_type or "unknown", maxlen=40)
    safe_name = _safe_seg(disp_name or item_id or "unnamed")
    id8       = (item_id or "")[:8]
    item_dir  = (output_root / run_label
                 / f"{safe_ws}__{ws_id}"
                 / safe_type
                 / f"{safe_name}__{id8}")

    # Lakehouse (metadata-only) — no getDefinition call
    if item_type in _METADATA_ONLY_TYPES:
        if handler_cls is None:
            base_row["error"] = f"No handler for metadata-only type {item_type!r}."
            return base_row
        files = handler_cls().to_files(item, {})
        return _write_files(item_dir, files, base_row, skip_existing,
                            include_raw, {})

    # Generic items with getDefinition
    format_hint = None
    if item_type == "Notebook" and notebook_format == "ipynb":
        format_hint = "ipynb"

    definition = _fetch_definition_sync(
        ws_id, item_id, token, fabric_base, format_hint
    )
    if definition is None:
        base_row["error"] = "getDefinition returned no body."
        return base_row

    if handler_cls is None:
        # Fallback: generic parts handler even for unregistered types.
        from .item_types import generic_parts_to_files
        files = generic_parts_to_files(definition)
    elif item_type == "Notebook":
        files = handler_cls().to_files(item, definition,
                                       notebook_format=notebook_format)
    else:
        files = handler_cls().to_files(item, definition)

    return _write_files(item_dir, files, base_row, skip_existing,
                        include_raw, definition)


def _write_files(
    item_dir: Path,
    files: dict[str, bytes],
    base_row: dict,
    skip_existing: bool,
    include_raw: bool,
    raw_definition: dict,
) -> dict:
    if not files:
        base_row["error"] = "Handler produced no files."
        return base_row

    # Compute sha256 over all content concatenated (deterministic ordering)
    combined = b"".join(v for _, v in sorted(files.items()))
    base_row["sha256"] = _sha256(combined)
    base_row["bytes"]  = len(combined)

    written = 0
    for rel, data in files.items():
        dest = item_dir / rel
        if skip_existing and dest.exists():
            continue
        _write_file(dest, data)
        written += 1

    if include_raw and raw_definition:
        raw_dest = item_dir / "_definition.json"
        if not (skip_existing and raw_dest.exists()):
            _write_file(raw_dest, json.dumps(raw_definition, indent=1).encode("utf-8"))

    base_row["status"] = "ok" if written > 0 else "skipped_exists"
    return base_row


# ---------------------------------------------------------------------------
# Manifest writer
# ---------------------------------------------------------------------------


def _write_manifest(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    log.info("Manifest written to %s", path)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI entry-point.  Returns an exit code (0 = success)."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s  %(message)s",
    )

    try:
        item_types = resolve_item_types(args.item_types, args.exclude_item_types)
    except ValueError as exc:
        parser.error(str(exc))
        return 2

    token = _acquire_token(args)

    try:
        rows = download_items(args, item_types, token)
    except Exception as exc:
        log.error("Download failed: %s", exc)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1

    # Determine manifest path
    run_label = args.run_label or _auto_run_label()
    manifest_path = (
        Path(args.manifest)
        if args.manifest
        else Path(args.output) / run_label / "_manifest.json"
    )
    _write_manifest(rows, manifest_path)

    ok      = sum(1 for r in rows if r["status"] == "ok")
    skipped = sum(1 for r in rows if r["status"] == "skipped_exists")
    errors  = sum(1 for r in rows if r["status"] == "error")
    print(
        f"Done — {len(rows)} items: "
        f"{ok} downloaded, {skipped} skipped, {errors} errors.",
        file=sys.stderr,
    )
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
