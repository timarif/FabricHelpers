"""Split plan builder and report writer.

Generates ``splitter_report.csv`` and ``splitter_report.json`` with one row
per item showing the proposed target workspace and action.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Action = Literal["move", "leave"]
Target = Literal["A", "B"]


@dataclass(frozen=True)
class PlanRow:
    """One row in the split plan."""

    item_id: str
    item_type: str
    name: str
    source_workspace_id: str
    target_workspace: Target
    target_workspace_id: str
    action: Action


def build_plan(
    items: list[dict],
    classification: dict[str, str],
    workspace_a_id: str,
    workspace_b_id: str,
    source_workspace_id: str,
) -> list[PlanRow]:
    """Build the full split plan from classified items.

    Parameters
    ----------
    items:
        Raw item dicts from the Fabric Items API.
    classification:
        Mapping of ``item_id → "A" | "B"`` produced by :func:`classify`.
    workspace_a_id:
        Target workspace ID for group A items.
    workspace_b_id:
        Target workspace ID for group B items.
    source_workspace_id:
        The workspace being split.  Items whose target matches the source
        receive ``action="leave"`` (already in the right place).

    Returns
    -------
    List of :class:`PlanRow` instances, one per item.
    """
    rows: list[PlanRow] = []
    for item in items:
        item_id = item.get("id", "")
        if not item_id:
            continue
        target: Target = classification.get(item_id, "B")  # type: ignore[assignment]
        target_ws_id = workspace_a_id if target == "A" else workspace_b_id
        action: Action = "leave" if target_ws_id == source_workspace_id else "move"
        rows.append(
            PlanRow(
                item_id=item_id,
                item_type=item.get("type") or item.get("itemType") or "",
                name=item.get("displayName") or item.get("name") or item_id,
                source_workspace_id=source_workspace_id,
                target_workspace=target,
                target_workspace_id=target_ws_id,
                action=action,
            )
        )
    return rows


_CSV_FIELDS = [
    "itemId",
    "itemType",
    "name",
    "sourceWorkspaceId",
    "targetWorkspace",
    "targetWorkspaceId",
    "action",
]


def _row_to_dict(row: PlanRow) -> dict:
    return {
        "itemId": row.item_id,
        "itemType": row.item_type,
        "name": row.name,
        "sourceWorkspaceId": row.source_workspace_id,
        "targetWorkspace": row.target_workspace,
        "targetWorkspaceId": row.target_workspace_id,
        "action": row.action,
    }


def write_plan(rows: list[PlanRow], output_dir: Path) -> tuple[Path, Path]:
    """Write *rows* to ``splitter_report.csv`` and ``splitter_report.json``.

    Parameters
    ----------
    rows:
        Plan rows produced by :func:`build_plan`.
    output_dir:
        Directory where the report files are written (created if missing).

    Returns
    -------
    ``(csv_path, json_path)`` tuple.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "splitter_report.csv"
    json_path = output_dir / "splitter_report.json"

    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(_row_to_dict(row))

    with json_path.open("w", encoding="utf-8") as fh:
        json.dump([_row_to_dict(row) for row in rows], fh, indent=2)

    return csv_path, json_path
