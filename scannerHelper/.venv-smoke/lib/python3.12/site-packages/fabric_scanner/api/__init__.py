"""Optional Fabric REST API helpers — auth, workspace/notebook enumeration,
and notebook content fetch with LRO polling.

This subpackage is only useful when the package is installed with the
`[api]` extra (`pip install fabric-scanner[api]`) which adds aiohttp +
requests. Importing `fabric_scanner.api` without those deps will fail at
the leaf modules that need them; the top-level `fabric_scanner` import
stays clean either way.
"""
from .auth      import get_token, TokenError
from .enumerate import enumerate_notebooks, run_enumeration_sync
from .fetch     import fetch_notebook_definition

__all__ = [
    "get_token", "TokenError",
    "enumerate_notebooks", "run_enumeration_sync",
    "fetch_notebook_definition",
]
