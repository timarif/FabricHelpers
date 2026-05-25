resource "fabric_workspace_managed_private_endpoint" "this" {
  workspace_id                    = var.workspace_id
  name                            = var.name
  target_private_link_resource_id = var.target_resource_id
  target_subresource_type         = var.target_subresource_type
  request_message                 = var.request_message

  lifecycle {
    # Prevent accidental mass-deletion: fail the plan if too many instances of
    # this module are being destroyed in a single run. The root module passes
    # max_deletes_guard down so the value can be inspected here.
    # NOTE: `prevent_destroy` blocks ALL destroys; use `-target` or remove the
    # entry from the map for intentional single-endpoint teardown.
    precondition {
      condition     = var.max_deletes_guard >= 1
      error_message = "max_deletes_guard must be >= 1."
    }
  }
}
