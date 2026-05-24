locals {
  # Embed the run_label into every request_message when provided.
  # The approve_pending.py script matches on this prefix to scope approvals
  # to exactly the PECs created during this Terraform run.
  endpoints_with_label = {
    for k, v in var.managed_private_endpoints : k => merge(v, {
      request_message = (
        var.run_label != ""
        ? "[run=${var.run_label}] ${v.request_message}"
        : v.request_message
      )
    })
  }
}

module "mpe" {
  for_each = local.endpoints_with_label
  source   = "./modules/managed_private_endpoint"

  workspace_id            = each.value.workspace_id
  name                    = each.value.name
  target_resource_id      = each.value.target_resource_id
  target_subresource_type = each.value.target_subresource_type
  request_message         = each.value.request_message

  # Safety cap: fail the plan before any API call if too many deletions
  # are planned. The count of resources already in state minus the count
  # in the new plan gives the number of deletions.
  max_deletes_guard = var.max_deletes_guard
}
