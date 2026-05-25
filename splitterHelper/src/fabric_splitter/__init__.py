"""fabric-splitter — split a Fabric workspace into two by item type.

Public API (stable from v0.1):

    >>> from fabric_splitter import classify, build_plan, write_plan
    >>> items = [{"id": "i1", "type": "Notebook", "displayName": "NB1"}]
    >>> classification = classify(items, types_to_a={"notebook"})
    >>> from fabric_splitter.plan import build_plan, write_plan

The CLI entrypoint ``fabric-splitter`` is installed by the package and
provides ``--dry-run`` (default) and ``--apply`` modes.
"""
from ._version import __version__
from .classify import classify

__all__ = [
    "classify",
    "__version__",
]
