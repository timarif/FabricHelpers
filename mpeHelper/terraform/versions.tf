terraform {
  required_version = ">= 1.5"

  required_providers {
    fabric = {
      source  = "microsoft/fabric"
      version = "~> 1.5"
    }
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }
}
