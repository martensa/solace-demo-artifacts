# =============================================================================
# Event Mesh: DMR clusters and links between solace-1 and solace-2
#
# Bridges reference VPN names as strings, so explicit depends_on ensures
# the VPNs exist before DMR bridges are created.
# =============================================================================

# --- Solace-1 side (initiator = local) ---

module "solace_1_dmr" {
  source    = "./modules/dmr"
  providers = { solacebroker = solacebroker.solace_1 }

  depends_on = [
    module.solace_1_vpn_default,
    module.solace_1_vpn_amartens_test,
  ]

  cluster_name     = "cluster-solace-1"
  cluster_password = var.dmr_password
  remote_node      = "solace-2"
  remote_address   = "solace-2:55555"
  initiator        = "local"
  enabled          = var.dmr_enabled

  bridge_vpn_pairs = [
    { local_vpn = "default", remote_vpn = "default" },
    { local_vpn = "amartens-test", remote_vpn = "amartens-test" },
  ]
}

# --- Solace-2 side (initiator = remote, waits for solace-1) ---

module "solace_2_dmr" {
  source    = "./modules/dmr"
  providers = { solacebroker = solacebroker.solace_2 }

  depends_on = [
    module.solace_2_vpn_default,
    module.solace_2_vpn_amartens_test,
  ]

  cluster_name     = "cluster-solace-2"
  cluster_password = var.dmr_password
  remote_node      = "solace-1"
  initiator        = "remote"
  enabled          = var.dmr_enabled

  bridge_vpn_pairs = [
    { local_vpn = "default", remote_vpn = "default" },
    { local_vpn = "amartens-test", remote_vpn = "amartens-test" },
  ]
}
