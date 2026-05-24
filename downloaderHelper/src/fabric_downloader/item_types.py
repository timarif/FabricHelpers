"""Item-type registry for fabric-downloader.

Each Fabric item type is represented by a :class:`ItemHandler` subclass that
knows how to:

1. Report its ``item_type`` string (the value the Fabric Items API returns in
   the ``type`` field, e.g. ``"Notebook"``, ``"Report"``).
2. Convert a raw ``getDefinition`` response body to a flat
   ``{relative_path: bytes}`` mapping (``to_files``).

The global :data:`REGISTRY` maps lower-cased item-type strings to handler
classes.  Use the :func:`register` decorator to enlist a new handler — it is
idempotent but raises ``ValueError`` on a duplicate registration with a
*different* class.

Usage::

    from fabric_downloader.item_types import REGISTRY, ItemHandler

    handler_cls = REGISTRY.get("notebook")
    if handler_cls:
        files = handler_cls().to_files(item_meta, definition_body)
"""
from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from typing import ClassVar


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class ItemHandler(ABC):
    """Abstract base for per-item-type download handlers.

    Subclasses must set :attr:`item_type` and implement :meth:`to_files`.
    """

    item_type: ClassVar[str]
    """Fabric API ``type`` string (exact casing), e.g. ``"Notebook"``."""

    default_format: ClassVar[str] = "parts"
    """Default serialisation mode used when no per-type override is given.
    Most handlers leave this as ``"parts"``; the notebook handler overrides
    it to ``"py"``."""

    @abstractmethod
    def to_files(
        self,
        item: dict,
        definition: dict,
    ) -> dict[str, bytes]:
        """Convert a ``getDefinition`` response body to saveable files.

        Parameters
        ----------
        item:
            Item metadata dict (at minimum ``id``, ``displayName``,
            ``workspaceId``, ``type``).
        definition:
            Parsed JSON body from ``POST /items/{id}/getDefinition``.
            Contains ``definition.parts`` for most types.

        Returns
        -------
        dict[str, bytes]
            Mapping of ``relative_path -> raw bytes``.  Paths are relative
            to the item's output folder (``<ws>/<type>/<name>__<id8>/``).
            The caller is responsible for writing the bytes to disk.
        """


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


REGISTRY: dict[str, type[ItemHandler]] = {}
"""Global mapping ``item_type.lower() -> ItemHandler subclass``."""


def register(cls: type[ItemHandler]) -> type[ItemHandler]:
    """Class decorator — add *cls* to :data:`REGISTRY`.

    Raises ``ValueError`` when a *different* class attempts to claim the
    same key (protects against accidental shadowing).  Re-registering the
    same class is a no-op.
    """
    key = cls.item_type.lower()
    existing = REGISTRY.get(key)
    if existing is not None and existing is not cls:
        raise ValueError(
            f"Item type {cls.item_type!r} is already registered "
            f"by {existing.__name__!r}; cannot register {cls.__name__!r}."
        )
    REGISTRY[key] = cls
    return cls


# ---------------------------------------------------------------------------
# Shared helpers used by handlers
# ---------------------------------------------------------------------------


def _decode_part(part: dict) -> bytes:
    """Base64-decode the ``payload`` field of a definition part."""
    raw = part.get("payload") or ""
    if not raw:
        return b""
    return base64.b64decode(raw)


def _parts_from_body(body: dict) -> list[dict]:
    """Extract the parts list from a ``getDefinition`` response."""
    return (body.get("definition") or {}).get("parts") or []


def _safe_path(raw: str) -> str:
    """Sanitize a part path so it can be used as a file name component.

    Replaces ``/`` with ``__`` and strips any leading dots so the result is
    safe as a filesystem name segment.
    """
    safe = raw.strip("/").replace("/", "__")
    safe = safe.lstrip(".")
    return safe or "part"


def generic_parts_to_files(body: dict) -> dict[str, bytes]:
    """Default implementation of ``to_files`` for any parts-based handler.

    Decodes every non-empty part from ``definition.parts`` and returns a
    mapping of ``{<safe_path>.bin -> raw_bytes}`` plus a ``<safe_path>.txt``
    entry when the payload is valid UTF-8.  This is the fallback used by
    every handler that does not need special treatment.
    """
    out: dict[str, bytes] = {}
    for part in _parts_from_body(body):
        raw_path = (part.get("path") or "").strip("/")
        if not raw_path:
            continue
        data = _decode_part(part)
        if not data:
            continue
        out[raw_path] = data
    return out
