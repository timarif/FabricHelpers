"""Item-type classification — pure logic, no I/O.

Given a list of Fabric item dicts and a set of type names, classifies each
item as belonging to workspace A or workspace B.
"""
from __future__ import annotations


def classify(items: list[dict], types_to_a: set[str]) -> dict[str, str]:
    """Map ``item_id → 'A' | 'B'``.

    Items whose ``type`` (case-insensitive) is in *types_to_a* → workspace A.
    Everything else → workspace B.

    Parameters
    ----------
    items:
        List of item dicts from the Fabric Items API.  Each dict must contain
        at least ``id`` and ``type`` (or ``itemType``) keys.
    types_to_a:
        Set of item-type strings (case-insensitive) that should go to
        workspace A.  Empty set → all items go to B.

    Returns
    -------
    dict mapping ``item_id → "A" | "B"``.  Items with no ``id`` are skipped.
    """
    normalized = {t.strip().lower() for t in types_to_a if t.strip()}
    result: dict[str, str] = {}
    for item in items:
        item_id = item.get("id", "")
        if not item_id:
            continue
        item_type = (item.get("type") or item.get("itemType") or "").strip().lower()
        result[item_id] = "A" if item_type in normalized else "B"
    return result
