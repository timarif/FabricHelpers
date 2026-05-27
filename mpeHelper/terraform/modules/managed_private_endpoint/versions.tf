terraform {
  required_version = ">= 1.5"

  # Submodules must redeclare every provider they use; otherwise Terraform
  # defaults the source address to `hashicorp/<name>` (which does not exist
  # for `fabric`) and `terraform init` fails with
  # `Failed to query available provider packages: registry.terraform.io does
  # not have a provider named registry.terraform.io/hashicorp/fabric`.
  required_providers {
    fabric = {
      source  = "microsoft/fabric"
      version = "~> 0.1"
    }
  }
}
