terraform {
  required_providers {
    solacebroker = {
      source = "registry.terraform.io/solaceproducts/solacebroker"
    }
  }
}

# --- DMR Cluster ---

resource "solacebroker_dmr_cluster" "this" {
  dmr_cluster_name              = var.cluster_name
  authentication_basic_enabled  = true
  authentication_basic_password = var.cluster_password
  enabled                       = true

  lifecycle {
    prevent_destroy = true
  }
}

# --- DMR Cluster Link ---

resource "solacebroker_dmr_cluster_link" "this" {
  dmr_cluster_name              = solacebroker_dmr_cluster.this.dmr_cluster_name
  remote_node_name              = var.remote_node
  authentication_basic_password = var.cluster_password
  enabled                       = var.enabled
  initiator                     = var.initiator
  span                          = "external"
}

# --- Remote Address (only for the initiating side) ---

resource "solacebroker_dmr_cluster_link_remote_address" "this" {
  count = var.remote_address != "" ? 1 : 0

  dmr_cluster_name = solacebroker_dmr_cluster.this.dmr_cluster_name
  remote_node_name = solacebroker_dmr_cluster_link.this.remote_node_name
  remote_address   = var.remote_address
}

# --- DMR Bridges (one per VPN pair) ---

resource "solacebroker_msg_vpn_dmr_bridge" "this" {
  for_each = { for pair in var.bridge_vpn_pairs : "${pair.local_vpn}-${pair.remote_vpn}" => pair }

  msg_vpn_name        = each.value.local_vpn
  remote_node_name    = var.remote_node
  remote_msg_vpn_name = each.value.remote_vpn

  depends_on = [solacebroker_dmr_cluster.this]
}
