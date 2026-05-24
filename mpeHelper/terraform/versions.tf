terraform {
  required_version = ">= 1.5"

  required_providers {
    fabric = {
      source  = "microsoft/fabric"
      version = "~> 0.1"
    }
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }
}
