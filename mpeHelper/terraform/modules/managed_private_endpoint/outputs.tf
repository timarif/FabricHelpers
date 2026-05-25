output "mpe_id" {
  description = "Fabric-side Managed Private Endpoint ID (GUID)."
  value       = fabric_workspace_managed_private_endpoint.this.id
}

output "workspace_id" {
  description = "Workspace ID this MPE belongs to."
  value       = fabric_workspace_managed_private_endpoint.this.workspace_id
}

output "name" {
  description = "Display name of the Managed Private Endpoint."
  value       = fabric_workspace_managed_private_endpoint.this.name
}

output "provisioning_state" {
  description = "Current provisioning state of the endpoint (Provisioning, Succeeded, Deleting, Failed, Updating)."
  value       = fabric_workspace_managed_private_endpoint.this.provisioning_state
}
