terraform {
  required_providers {
    solacebroker = {
      source = "registry.terraform.io/solaceproducts/solacebroker"
    }
  }
}

resource "solacebroker_msg_vpn_client_username" "this" {
  msg_vpn_name        = var.vpn_name
  client_username     = var.client_username
  password            = var.client_password
  enabled             = var.enabled
  acl_profile_name    = var.acl_profile_name
  client_profile_name = var.client_profile_name
}
