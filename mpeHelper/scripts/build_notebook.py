"""Generate the thin orchestration notebook for fabric-mpe."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fabric_core.build_notebook import (
    NotebookBuildSpec,
    _code as _core_code,
    _load_version,
    _md as _core_md,
    write_notebook,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_OUT = ROOT / "notebooks" / "mpe_manager.ipynb"
VERSION_FILE = ROOT / "src" / "fabric_mpe" / "_version.py"

_SYNAPSE_KERNEL = {
    "name": "synapse_pyspark",
    "display_name": "Synapse PySpark",
    "language": "python",
}


def _md(*lines: str) -> dict[str, str]:
    return _core_md("\n".join(lines))


def _code(*lines: str) -> dict[str, str]:
    return _core_code("\n".join(lines))


def cells(version: str) -> list[dict[str, str]]:
    return [
        _md(
            "# Fabric Managed Private Endpoint Manager",
            "",
            f"_Thin orchestrator over `fabric-mpe=={version}`._",
            "",
            "Run cells top-to-bottom. Each step is gated by an explicit",
            "flag on `MpeConfig` and capped by a hard limit, so nothing",
            "destructive happens by accident:",
            "",
            "```",
            "INVENTORY  \u2192  DRY-RUN  \u2192  DELETE  \u2192  RECREATE  \u2192  APPROVE",
            "```",
            "",
            "All MPE logic lives in the installable wheel; edits to filter,",
            "audit schema, or REST behavior happen there, not in this notebook.",
            "See [`mpeHelper/README.md`](../README.md) for full configuration",
            "and table layouts.",
        ),
        _code(
            "# Install the MPE wheel (re-run when you bump the version).",
            f"%pip install -q fabric-mpe=={version}",
        ),
        _md(
            "## 1. Configuration",
            "",
            "`MpeConfig` is a frozen dataclass \u2014 every knob has a sensible",
            "default. The most common edits are commented inline. Use",
            "`dataclasses.replace(cfg, commit=True)` (or just rebuild `cfg`",
            "with the flag flipped) when you're ready to move from preview",
            "to commit.",
        ),
        _code(
            "from fabric_mpe import MpeConfig",
            "",
            "cfg = MpeConfig(",
            "    # --- Workspace scope -----------------------------------------",
            "    workspace_scope = \"visible\",   # \"visible\" | \"list\" | \"from_inventory\"",
            "    # workspaces      = (\"<ws-guid-1>\", \"<ws-guid-2>\"),  # required when scope=\"list\"",
            "",
            "    # --- Persistence ---------------------------------------------",
            "    inventory_table = \"mpe_inventory\",",
            "    audit_table     = \"mpe_delete_audit\",",
            "    recreate_table  = \"mpe_recreate_audit\",",
            "    approve_table   = \"mpe_approve_audit\",",
            "    # write_schema   = \"bronze\",        # optional schema/database",
            "    files_subdir   = \"mpe_manager\",",
            "",
            "    # --- Filters (apply in dry-run / commit / recreate) ----------",
            "    # name_filter   = r\"^prod-\",",
            "    # id_filter     = (\"mpe-guid-1\",),",
            "    # target_filter = r\"storageAccounts\",",
            "",
            "    # --- Deletion safety -----------------------------------------",
            "    commit      = False,   # set True ONLY when you really want to delete",
            "    max_deletes = 25,",
            "",
            "    # --- Recreate (defaults to recreating what we just deleted) --",
            "    recreate                 = False,",
            "    recreate_source          = \"audit\",   # \"audit\" | \"inventory\"",
            "    recreate_request_message = \"Recreated via fabric-mpe\",",
            "    max_recreates            = 25,",
            "",
            "    # --- Approve (auto-approve Pending PECs on the Azure side) ---",
            "    approve             = False,",
            "    approve_description = \"Approved by fabric-mpe\",",
            "    max_approves        = 25,",
            ")",
            "print(f\"Run label   : {cfg.run_label}\")",
            "print(f\"Scope       : {cfg.workspace_scope}\")",
            "print(f\"Commit mode : {cfg.commit}   (max_deletes={cfg.max_deletes})\")",
            "print(f\"Recreate    : {cfg.recreate} (source={cfg.recreate_source!r}, \"",
            "      f\"max_recreates={cfg.max_recreates})\")",
            "print(f\"Approve     : {cfg.approve} (max_approves={cfg.max_approves})\")",
        ),
        _md(
            "## 2. Diagnostics \u2014 probe endpoints",
            "",
            "Prints the standard four-endpoint banner plus an MPE-specific",
            "`list /managedPrivateEndpoints` probe against the first visible",
            "workspace. Safe to run any time \u2014 read-only.",
        ),
        _code(
            "from fabric_mpe import probe",
            "",
            "probe(cfg)",
        ),
        _md(
            "## 3. Inventory",
            "",
            "Walks every workspace in scope, lists MPEs, writes",
            "`Files/<files_subdir>/<run_label>/inventory.{json,csv}`, and",
            "appends a row per MPE to the Delta inventory table.",
        ),
        _code(
            "from fabric_mpe import inventory",
            "",
            "inv = inventory.run(cfg, spark)",
            "print(f\"Inventory : {len(inv.rows)} MPE(s) across \"",
            "      f\"{len(inv.workspace_ids)} workspace(s); {len(inv.skipped)} skipped.\")",
            "print(f\"Files     : {inv.files_dir}\")",
            "print(f\"Delta     : {inv.inventory_table}\")",
            "",
            "if inv.rows:",
            "    display(spark.read.table(inv.inventory_table)",
            "                  .where(f\"run_label = '{inv.run_label}'\")",
            "                  .orderBy(\"workspace_name\", \"mpe_name\"))",
        ),
        _md(
            "## 4. Dry-run deletion",
            "",
            "Applies `name_filter` / `id_filter` / `target_filter` to this",
            "run's inventory and prints the MPEs `delete.commit` *would*",
            "remove. No HTTP calls; safe to run at any time.",
        ),
        _code(
            "from fabric_mpe import delete",
            "",
            "targets = delete.dry_run(cfg, spark)",
            "print(f\"Filters match {len(targets)} MPE(s):\")",
            "for m in targets[:50]:",
            "    print(f\"  - ws={m['workspace_id']} mpe={m['mpe_id']} \"",
            "          f\"({m.get('mpe_name')!r}) -> {m.get('target_resource_id')}\")",
            "if len(targets) > 50:",
            "    print(f\"  ... and {len(targets) - 50} more\")",
        ),
        _md(
            "## 5. Commit deletion",
            "",
            "Deletes MPEs and logs every result to the audit Delta table.",
            "Gated by `cfg.commit=True`; refuses to run when the match count",
            "exceeds `cfg.max_deletes`.",
        ),
        _code(
            "result = delete.commit(cfg, spark)",
            "if not cfg.commit:",
            "    print(f\"COMMIT=False; skipping. {len(result.targets)} MPE(s) would be deleted.\")",
            "else:",
            "    print(f\"Done: {result.succeeded} deleted, {result.failed} failed.\")",
            "    if result.audit_rows:",
            "        display(spark.read.table(result.audit_table)",
            "                      .where(f\"run_label = '{result.run_label}'\")",
            "                      .orderBy(\"delete_status\", \"mpe_name\"))",
        ),
        _md(
            "## 6. Recreate",
            "",
            "Rebuilds MPEs from this run's delete audit (default) or any",
            "inventory snapshot. Gated by `cfg.recreate=True`. Each create",
            "request's `requestMessage` is prefixed with `[run=<run_label>]`",
            "so step 7 can match the resulting Pending PECs.",
        ),
        _code(
            "from fabric_mpe import recreate",
            "",
            "rec = recreate.run(cfg, spark)",
            "if not cfg.recreate:",
            "    print(f\"RECREATE=False; would recreate {len(rec.targets)} MPE(s).\")",
            "else:",
            "    print(f\"Done: {rec.succeeded} created, {rec.failed} failed.\")",
            "    if rec.audit_rows:",
            "        display(spark.read.table(rec.audit_table)",
            "                      .where(f\"run_label = '{rec.run_label}'\")",
            "                      .orderBy(\"create_status\", \"mpe_name\"))",
        ),
        _md(
            "## 7. Approve",
            "",
            "Auto-approves the Azure-side Pending privateEndpointConnections",
            "created by step 6. Uses an ARM-audience token (see the README",
            "for `ARM_TOKEN` / `ARM_SPN_*` env var escape hatches in",
            "cross-tenant scenarios).",
        ),
        _code(
            "from fabric_mpe import approve",
            "",
            "app = approve.run(cfg, spark)",
            "if not cfg.approve:",
            "    print(f\"APPROVE=False; would approve {len(app.queue)} PEC(s).\")",
            "else:",
            "    print(f\"Done: {app.succeeded} approved, {app.failed} failed, \"",
            "          f\"{len(app.list_errors)} LIST error(s).\")",
            "    if app.audit_rows:",
            "        display(spark.read.table(app.audit_table)",
            "                      .where(f\"run_label = '{app.run_label}'\")",
            "                      .orderBy(\"approve_status\", \"pec_name\"))",
        ),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT,
        help=f"output .ipynb path (default: {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--version", default=None,
        help="override the pinned mpe version (default: read from _version.py)",
    )
    args = parser.parse_args(argv)

    version = args.version or _load_version(VERSION_FILE)

    spec = NotebookBuildSpec(
        package_name="fabric-mpe",
        version=version,
        cells=cells(version),
        output_path=args.out,
        kernel_name="synapse_pyspark",
        language_name="python",
        metadata={"kernelspec": _SYNAPSE_KERNEL},
    )
    written = write_notebook(spec)
    print(f"Wrote {written}  (pinned fabric-mpe=={version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
