# ---------------------------------------------------------------------------
# Fabric provider
# ---------------------------------------------------------------------------
# Credentials are resolved in this order (mirrors the notebook's get_token()):
#   1. FABRIC_TENANT_ID + FABRIC_CLIENT_ID + FABRIC_CLIENT_SECRET  — SPN
#   2. FABRIC_TENANT_ID + FABRIC_CLIENT_ID + FABRIC_USE_CLI = true  — az login
#   3. Standard Azure SDK env vars (AZURE_TENANT_ID / AZURE_CLIENT_ID / ...)
#
# See: https://registry.terraform.io/providers/microsoft/fabric/latest/docs
provider "fabric" {}

# ---------------------------------------------------------------------------
# Azure RM provider  (used only by approve_pending.py — not by Terraform itself)
# ---------------------------------------------------------------------------
# The azurerm provider block is declared here so `terraform validate` succeeds.
# PEC approval is performed by the post-apply Python script approve_pending.py,
# which uses azure-identity DefaultAzureCredential directly, because
# azurerm_private_endpoint_connection currently lacks an approval resource.
provider "azurerm" {
  features {}
}
