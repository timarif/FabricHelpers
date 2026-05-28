"""fabric-tenant — snapshot and diff Microsoft Fabric admin tenant settings
across two physically different Fabric tenants.

This wheel is in early scaffolding (Phase 1). The public API stabilizes once
Phase 2 (auth + snapshot) and Phase 3 (normalize + diff) land. Tracking issue:
https://github.com/timarif/FabricHelpers/issues/44

Planned public surface (from Phase 3 onward):

    >>> from fabric_tenant import load_profiles, snapshot_tenant, diff_snapshots
    >>> profiles = load_profiles("tenants.yaml")
    >>> snap_a = snapshot_tenant(profiles["prod"])
    >>> snap_b = snapshot_tenant(profiles["test"])
    >>> diffs = diff_snapshots(snap_a, snap_b)

The ``fabric-tenant`` console script is the user-facing entrypoint.
"""
from ._version import __version__

__all__ = [
    "__version__",
]
