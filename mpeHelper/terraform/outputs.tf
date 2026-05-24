output "managed_private_endpoints" {
  description = "Details of every managed MPE after apply, keyed by the same logical name used in var.managed_private_endpoints."
  value = {
    for k, mod in module.mpe : k => {
      mpe_id             = mod.mpe_id
      workspace_id       = mod.workspace_id
      name               = mod.name
      provisioning_state = mod.provisioning_state
    }
  }
}

output "auto_approve" {
  description = "Whether the post-apply approve_pending.py script should be run. Mirrors var.auto_approve."
  value       = var.auto_approve
}
