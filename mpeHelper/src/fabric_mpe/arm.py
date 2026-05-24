"""ARM resource-provider / api-version helpers for privateEndpointConnections.

Conservative GA versions per RP, harvested from the legacy
``mpe_manager.ipynb`` cell 2. Override the dict (in code) if your RP
isn't listed; ``_PEC_DEFAULT_API_VERSION`` is the fallback.
"""
from __future__ import annotations

PEC_API_VERSIONS: dict[str, str] = {
    "Microsoft.Storage/storageAccounts":              "2023-05-01",
    "Microsoft.Sql/servers":                          "2023-08-01-preview",
    "Microsoft.KeyVault/vaults":                      "2023-07-01",
    "Microsoft.DocumentDB/databaseAccounts":          "2023-04-15",
    "Microsoft.EventHub/namespaces":                  "2024-01-01",
    "Microsoft.ServiceBus/namespaces":                "2022-10-01-preview",
    "Microsoft.Synapse/workspaces":                   "2021-06-01",
    "Microsoft.Search/searchServices":                "2023-11-01",
    "Microsoft.CognitiveServices/accounts":           "2023-05-01",
    "Microsoft.AppConfiguration/configurationStores": "2023-03-01",
    "Microsoft.Web/sites":                            "2023-12-01",
    "Microsoft.ContainerRegistry/registries":         "2023-11-01-preview",
    "Microsoft.DataFactory/factories":                "2018-06-01",
    "Microsoft.Purview/accounts":                     "2021-12-01",
}
PEC_DEFAULT_API_VERSION = "2023-09-01"


def rp_from_resource_id(resource_id: str | None) -> str | None:
    """Return ``'Microsoft.X/typeY'`` from an Azure resource id, else ``None``.

    Accepts ids of the form
    ``/subscriptions/.../providers/<RP>/<type>/<name>[/...]``.
    """
    if not resource_id:
        return None
    parts = resource_id.split("/providers/", 1)
    if len(parts) < 2:
        return None
    seg = parts[1].split("/")
    if len(seg) < 2:
        return None
    return f"{seg[0]}/{seg[1]}"


def pec_api_version(resource_id: str | None) -> tuple[str, str | None]:
    """Return ``(api_version, rp)`` for a private-endpoint-connection call."""
    rp = rp_from_resource_id(resource_id)
    return PEC_API_VERSIONS.get(rp or "", PEC_DEFAULT_API_VERSION), rp


__all__ = [
    "PEC_API_VERSIONS",
    "PEC_DEFAULT_API_VERSION",
    "rp_from_resource_id",
    "pec_api_version",
]
