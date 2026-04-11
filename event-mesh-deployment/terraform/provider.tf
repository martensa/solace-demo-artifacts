terraform {
  required_version = ">= 1.5"

  required_providers {
    solacebroker = {
      source  = "registry.terraform.io/solaceproducts/solacebroker"
      version = "~> 1.2"
    }
  }
}

# Each broker gets its own aliased provider.
# All module calls must pass `providers = { solacebroker = solacebroker.<alias> }`.

provider "solacebroker" {
  alias    = "solace_1"
  url      = var.solace_1_url
  username = var.solace_1_username
  password = var.solace_1_password
}

provider "solacebroker" {
  alias    = "solace_2"
  url      = var.solace_2_url
  username = var.solace_2_username
  password = var.solace_2_password
}
