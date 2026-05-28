"""``fabric-splitter`` CLI — split a Fabric workspace into two by item type.

Usage examples
--------------
Dry-run (default) — print the proposed mapping without making changes::

    fabric-splitter \\
        --source <workspace-id> \\
        --workspace-a-name "Engineering WS" \\
        --workspace-b-name "Consumption WS" \\
        --types-to-a notebook,lakehouse,datapipeline,sparkjobdefinition

Apply the split::

    fabric-splitter \\
        --source <workspace-id> \\
        --workspace-a-name "Engineering WS" \\
        --workspace-b-name "Consumption WS" \\
        --types-to-a notebook,lakehouse,datapipeline,sparkjobdefinition \\
        --apply
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("fabric_splitter")
_DRY_RUN_PLACEHOLDER_PREFIX = "<would-create: "


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fabric-splitter",
        description=(
            "Split a Fabric workspace into two target workspaces along item-type lines."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--source",
        required=True,
        metavar="WORKSPACE_ID",
        help="ID of the source workspace to split.",
    )
    p.add_argument(
        "--workspace-a-name",
        required=True,
        metavar="NAME",
        help="Display name for workspace A (created if missing).",
    )
    p.add_argument(
        "--workspace-b-name",
        required=True,
        metavar="NAME",
        help="Display name for workspace B (created if missing).",
    )
    p.add_argument(
        "--types-to-a",
        required=True,
        metavar="TYPE[,TYPE…]",
        help=(
            "Comma-separated list of Fabric item types (case-insensitive) "
            "that go to workspace A.  Everything else goes to workspace B."
        ),
    )

    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        dest="apply",
        action="store_false",
        default=False,
        help="(Default) Print the proposed mapping without making any changes.",
    )
    mode.add_argument(
        "--apply",
        dest="apply",
        action="store_true",
        help="Create target workspaces and move items (mutates Fabric state).",
    )

    p.add_argument(
        "--skip-permissions",
        action="store_true",
        default=False,
        help=(
            "Do not copy workspace role assignments from source → targets "
            "(only relevant with --apply)."
        ),
    )
    p.add_argument(
        "--output-dir",
        metavar="PATH",
        default=".",
        help="Directory for the report CSV/JSON and audit log (default: current dir).",
    )
    p.add_argument(
        "--token",
        metavar="TOKEN",
        default=None,
        help=(
            "Bearer token for the Fabric REST API.  When omitted the token is "
            "resolved from notebookutils / FABRIC_BEARER_TOKEN env var / Azure CLI / "
            "DefaultAzureCredential (same chain as the rest of FabricHelpers)."
        ),
    )
    p.add_argument(
        "--fabric-base",
        metavar="URL",
        default="https://api.fabric.microsoft.com",
        help="Fabric REST API base URL (default: %(default)s).",
    )
    p.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=False,
        help="Enable debug logging.",
    )
    return p


def _get_token(token_arg: str | None) -> str:
    if token_arg:
        return token_arg
    try:
        from fabric_core.auth import get_token

        return get_token("https://api.fabric.microsoft.com")
    except Exception as exc:
        log.error("Could not acquire a Fabric bearer token: %s", exc)
        sys.exit(1)


def _list_workspace_items(
    workspace_id: str,
    token: str,
    fabric_base: str,
) -> list[dict]:
    from ._http import paged_get

    return paged_get(f"{fabric_base}/v1/workspaces/{workspace_id}/items", token)


def _list_items_across_workspaces(
    workspace_ids: list[str],
    token: str,
    fabric_base: str,
) -> list[dict]:
    items: list[dict] = []
    seen_workspaces: set[str] = set()
    seen_items: set[str] = set()

    for workspace_id in workspace_ids:
        if workspace_id in seen_workspaces:
            continue
        seen_workspaces.add(workspace_id)
        ws_items = _list_workspace_items(workspace_id, token, fabric_base)
        log.info("Found %d items in workspace %s.", len(ws_items), workspace_id)
        for item in ws_items:
            item_id = item.get("id")
            if item_id and item_id in seen_items:
                continue
            item_with_workspace = dict(item)
            item_with_workspace.setdefault("workspaceId", workspace_id)
            item_with_workspace["current_workspace_id"] = workspace_id
            items.append(item_with_workspace)
            if item_id:
                seen_items.add(item_id)

    return items


def main(argv: list[str] | None = None) -> int:  # noqa: C901  (complex but CLI entry)
    """CLI entrypoint.  Returns an exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    token = _get_token(args.token)
    output_dir = Path(args.output_dir)
    fabric_base: str = args.fabric_base
    types_to_a = {t.strip().lower() for t in args.types_to_a.split(",") if t.strip()}

    # ------------------------------------------------------------------ #
    # 1. Resolve / create target workspaces                                #
    # ------------------------------------------------------------------ #
    from .workspaces import (
        copy_role_assignments,
        get_or_create_workspace,
        get_workspace_id,
    )

    if args.apply:
        log.info("--apply mode: creating/verifying target workspaces …")
        try:
            workspace_a_id = get_or_create_workspace(
                args.workspace_a_name, token, fabric_base=fabric_base
            )
            workspace_b_id = get_or_create_workspace(
                args.workspace_b_name, token, fabric_base=fabric_base
            )
        except urllib.error.HTTPError as exc:
            log.error("Failed to create/verify target workspaces: HTTP %s", exc.code)
            return 1
    else:
        workspace_a_existing_id = get_workspace_id(
            args.workspace_a_name, token, fabric_base=fabric_base
        )
        workspace_b_existing_id = get_workspace_id(
            args.workspace_b_name, token, fabric_base=fabric_base
        )
        # Dry-run: use placeholder IDs when targets don't exist yet.
        workspace_a_id = (
            workspace_a_existing_id
            if workspace_a_existing_id
            else f"{_DRY_RUN_PLACEHOLDER_PREFIX}{args.workspace_a_name}>"
        )
        workspace_b_id = (
            workspace_b_existing_id
            if workspace_b_existing_id
            else f"{_DRY_RUN_PLACEHOLDER_PREFIX}{args.workspace_b_name}>"
        )

    # ------------------------------------------------------------------ #
    # 2. Discover items in source + targets                                #
    # ------------------------------------------------------------------ #
    workspace_ids_to_list = [args.source]
    if not workspace_a_id.startswith(_DRY_RUN_PLACEHOLDER_PREFIX):
        workspace_ids_to_list.append(workspace_a_id)
    if not workspace_b_id.startswith(_DRY_RUN_PLACEHOLDER_PREFIX):
        workspace_ids_to_list.append(workspace_b_id)

    log.info("Listing items in workspaces: %s", ", ".join(workspace_ids_to_list))
    try:
        items = _list_items_across_workspaces(workspace_ids_to_list, token, fabric_base)
    except urllib.error.HTTPError as exc:
        log.error("Failed to list items in one or more workspaces: HTTP %s", exc.code)
        return 1

    log.info("Found %d total items across listed workspaces.", len(items))

    # ------------------------------------------------------------------ #
    # 3. Classify items                                                    #
    # ------------------------------------------------------------------ #
    from .classify import classify

    classification = classify(items, types_to_a)
    a_count = sum(1 for v in classification.values() if v == "A")
    b_count = sum(1 for v in classification.values() if v == "B")
    log.info("Classification: %d → workspace A, %d → workspace B", a_count, b_count)

    # ------------------------------------------------------------------ #
    # 4. Build and write the plan report                                   #
    # ------------------------------------------------------------------ #
    from .plan import build_plan, write_plan

    plan = build_plan(
        items,
        classification,
        workspace_a_id=workspace_a_id,
        workspace_b_id=workspace_b_id,
        source_workspace_id=args.source,
    )
    csv_path, json_path = write_plan(plan, output_dir)
    log.info("Report written → %s  /  %s", csv_path, json_path)

    if not args.apply:
        log.info(
            "Dry-run complete.  Pass --apply to execute the split.\n"
            "Actions summary:\n"
            "  move  : %d items\n"
            "  leave : %d items",
            sum(1 for r in plan if r.action == "move"),
            sum(1 for r in plan if r.action == "leave"),
        )
        return 0

    # ------------------------------------------------------------------ #
    # 5. Apply: copy permissions (unless --skip-permissions)              #
    # ------------------------------------------------------------------ #
    if not args.skip_permissions:
        log.info("Copying role assignments to workspace A …")
        try:
            n = copy_role_assignments(
                args.source, workspace_a_id, token, fabric_base=fabric_base
            )
            log.info("  Copied %d assignments → workspace A", n)
        except Exception as exc:
            log.warning("Role-assignment copy to A failed: %s", exc)

        log.info("Copying role assignments to workspace B …")
        try:
            n = copy_role_assignments(
                args.source, workspace_b_id, token, fabric_base=fabric_base
            )
            log.info("  Copied %d assignments → workspace B", n)
        except Exception as exc:
            log.warning("Role-assignment copy to B failed: %s", exc)

    # ------------------------------------------------------------------ #
    # 6. Apply: move items                                                 #
    # ------------------------------------------------------------------ #
    from .move import move_item

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    audit_path = output_dir / f"splitter_audit_{ts}.jsonl"
    output_dir.mkdir(parents=True, exist_ok=True)

    errors = 0
    with audit_path.open("w", encoding="utf-8") as audit_fh:
        for row in plan:
            if row.action != "move":
                continue
            item = next((i for i in items if i.get("id") == row.item_id), None)
            if item is None:
                continue
            try:
                move_item(
                    item,
                    source_workspace_id=(
                        item.get("current_workspace_id")
                        or item.get("workspaceId")
                        or args.source
                    ),
                    target_workspace_id=row.target_workspace_id,
                    token=token,
                    audit_fh=audit_fh,
                    fabric_base=fabric_base,
                )
            except Exception as exc:
                log.error("Failed to move %s: %s", row.item_id, exc)
                errors += 1

    log.info("Audit log → %s", audit_path)

    # ------------------------------------------------------------------ #
    # 7. Apply: rewrite cross-workspace references                         #
    # ------------------------------------------------------------------ #
    from .rewrite import rewrite_references, REWRITE_CANDIDATES

    # Build a global routing map used by the rewriter's second pass.
    # For each planned item, route item_id -> post-split workspace_id.
    item_workspace_map: dict[str, str] = {}
    ambiguous_item_ids: set[str] = set()
    for row in plan:
        if row.item_id in ambiguous_item_ids:
            continue
        existing = item_workspace_map.get(row.item_id)
        if existing and existing != row.target_workspace_id:
            log.warning(
                "Skipping ambiguous routing for item %s: %s vs %s",
                row.item_id,
                existing,
                row.target_workspace_id,
            )
            item_workspace_map.pop(row.item_id, None)
            ambiguous_item_ids.add(row.item_id)
            continue
        item_workspace_map[row.item_id] = row.target_workspace_id

    # Build per-item id_maps for the rewriter's first pass.
    # Any mention of the source workspace ID should be replaced with the
    # rewriting item's own current (post-move) workspace ID.
    any_to_rewrite = any(
        row.action == "move" and row.target_workspace_id != args.source
        for row in plan
    )

    if any_to_rewrite:
        log.info("Running reference-rewrite pass …")
        for row in plan:
            # Leave rows are already at their target workspace and do not need
            # post-move reference rewriting.
            if row.action != "move":
                continue
            item = next((i for i in items if i.get("id") == row.item_id), None)
            if item is None:
                continue
            item_type = item.get("type") or item.get("itemType") or ""
            if item_type not in REWRITE_CANDIDATES:
                continue
            ws_id = row.target_workspace_id
            # Replace mentions of the source workspace ID with this item's
            # current (post-move) workspace ID.
            item_id_map = {args.source: ws_id}
            try:
                changed = rewrite_references(
                    item,
                    ws_id,
                    item_id_map,
                    token,
                    item_workspace_map,
                    fabric_base=fabric_base,
                )
                if changed:
                    log.info("  Rewrote references in %s", row.item_id)
            except Exception as exc:
                log.warning("  Reference rewrite failed for %s: %s", row.item_id, exc)

    # ------------------------------------------------------------------ #
    # 8. Summary                                                           #
    # ------------------------------------------------------------------ #
    moved = sum(1 for r in plan if r.action == "move")
    left = sum(1 for r in plan if r.action == "leave")
    log.info(
        "Split complete.  Moved: %d  Left: %d  Errors: %d",
        moved, left, errors,
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
