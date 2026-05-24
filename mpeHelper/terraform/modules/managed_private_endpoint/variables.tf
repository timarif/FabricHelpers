variable "workspace_id" {
  description = "Fabric workspace ID (GUID)."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.workspace_id))
    error_message = "workspace_id must be a valid UUID."
  }
}

variable "name" {
  description = "Display name of the Managed Private Endpoint within the workspace."
  type        = string

  validation {
    condition     = length(var.name) >= 1 && length(var.name) <= 128
    error_message = "name must be between 1 and 128 characters."
  }
}

variable "target_resource_id" {
  description = "ARM resource ID of the target Azure resource for which the private endpoint is created."
  type        = string

  validation {
    condition     = startswith(var.target_resource_id, "/subscriptions/")
    error_message = "target_resource_id must be a full ARM resource ID starting with /subscriptions/."
  }
}

variable "target_subresource_type" {
  description = "Sub-resource type of the target private link resource (e.g. 'blob', 'file', 'sqlServer', 'vault')."
  type        = string
  default     = null
}

variable "request_message" {
  description = "Message included with the private endpoint connection request."
  type        = string
  default     = "Managed by Terraform"

  validation {
    condition     = length(var.request_message) <= 140
    error_message = "request_message must be 140 characters or fewer (Fabric API limit)."
  }
}

variable "max_deletes_guard" {
  description = "Passed down from the root module; unused inside the module but required for the lifecycle precondition to fire at plan time."
  type        = number
  default     = 25
}
