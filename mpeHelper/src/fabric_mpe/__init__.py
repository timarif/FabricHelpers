"""fabric_mpe — manage Microsoft Fabric Managed Private Endpoints.

Public API (stable from v0.1):

    >>> from fabric_mpe import MpeConfig, inventory, delete, recreate, approve, probe
    >>> cfg = MpeConfig(workspace_scope="visible")
    >>> probe(cfg)
    >>> inv = inventory.run(cfg, spark)
    >>> targets = delete.dry_run(cfg, spark)
    >>> # set cfg.commit=True (replace cfg via dataclasses.replace) and re-run
    >>> result = delete.commit(cfg, spark)
    >>> rec = recreate.run(cfg, spark)
    >>> app = approve.run(cfg, spark)

All HTTP work is delegated to ``fabric_core.http`` and all token
acquisition to ``fabric_core.auth`` — the wheel stays Spark-runtime
agnostic and never calls ``display()`` itself.
"""
from . import api, approve, delete, inventory, persist, recreate
from ._version import __version__
from .auth import get_arm_token, get_fabric_token
from .config import MpeConfig
from .diagnostics import probe

__all__ = [
    "MpeConfig",
    "__version__",
    "api",
    "approve",
    "delete",
    "get_arm_token",
    "get_fabric_token",
    "inventory",
    "persist",
    "probe",
    "recreate",
]
