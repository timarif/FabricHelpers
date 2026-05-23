"""Optional Fabric REST API helpers — auth, item enumeration, and item
content fetch with LRO polling.

This subpackage is only useful when the package is installed with the
`[api]` extra (`pip install fabric-downloader[api]`) which adds aiohttp +
requests. Importing `fabric_downloader.api` without those deps will fail at
the leaf modules that need them; the top-level `fabric_downloader` import
stays clean either way.
"""
from .auth      import get_token, TokenError
from .enumerate import enumerate_items, run_enumeration_sync
from .fetch     import fetch_item_definition

__all__ = [
    "get_token", "TokenError",
    "enumerate_items", "run_enumeration_sync",
    "fetch_item_definition",
]
