# ---------------------------------------------------------------------------
# Managed Private Endpoints input map
# ---------------------------------------------------------------------------
# Key: any stable logical name (e.g. "ws_prod_storage_blob").
# The key never changes — it is what Terraform uses as the resource address
# and what `terraform import` must match.
variable "managed_private_endpoints" {
  description = <<-EOT
    Map of Managed Private Endpoints to manage, keyed by a stable logical name.

    Example:
      managed_private_endpoints = {
        "ws_prod_storage_blob" = {
          workspace_id             = "00000000-0000-0000-0000-000000000001"
          name                     = "myStorageBlob"
          target_resource_id       = "/subscriptions/.../storageAccounts/mysa"
          target_subresource_type  = "blob"
          request_message          = "Managed by Terraform"
        }
      }
  EOT

  type = map(object({
    workspace_id            = string
    name                    = string
    target_resource_id      = string
    target_subresource_type = optional(string, null)
    request_message         = optional(string, "Managed by Terraform")
  }))

  default = {}
}

# ---------------------------------------------------------------------------
# Run label (optional — mirrors the notebook's RUN_LABEL)
# ---------------------------------------------------------------------------
variable "run_label" {
  description = <<-EOT
    Optional label embedded into every request_message as "[run=<run_label>]".
    Enables the approve_pending.py script to match only PECs from this run.
    Leave empty to omit the prefix.
  EOT

  type    = string
  default = ""
}

# ---------------------------------------------------------------------------
# Safety cap
# ---------------------------------------------------------------------------
variable "max_deletes_guard" {
  description = <<-EOT
    Refuse to apply if more than this many MPEs are planned for deletion in a
    single run. Mirrors the notebook's MAX_DELETES knob. Enforced via a
    precondition on the module — Terraform will fail the plan before any
    destructive API call.
  EOT

  type    = number
  default = 25

  validation {
    condition     = var.max_deletes_guard >= 1
    error_message = "max_deletes_guard must be at least 1."
  }
}

# ---------------------------------------------------------------------------
# Auto-approve flag (informational — acted on by approve_pending.py)
# ---------------------------------------------------------------------------
variable "auto_approve" {
  description = <<-EOT
    When true, the post-apply approve_pending.py script should be run to
    approve the Pending Private Endpoint Connections on the Azure side.
    This variable is exposed as an output so the CI wrapper can read it.
  EOT

  type    = bool
  default = false
}
