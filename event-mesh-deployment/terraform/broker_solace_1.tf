# =============================================================================
# Solace-1: VPNs, clients, telemetry
# =============================================================================

# --- default VPN (all services enabled) ---

module "solace_1_vpn_default" {
  source    = "./modules/vpn"
  providers = { solacebroker = solacebroker.solace_1 }

  vpn_name                  = "default"
  services_enabled          = true
  semp_over_msg_bus_enabled = true
}

module "solace_1_client_default" {
  source    = "./modules/client"
  providers = { solacebroker = solacebroker.solace_1 }

  vpn_name        = module.solace_1_vpn_default.vpn_name
  client_username = "default"
  client_password = var.default_client_password
}

# --- amartens-test VPN (Event Portal environment for AMARTENS EVENT MESH) ---

module "solace_1_vpn_amartens_test" {
  source    = "./modules/vpn"
  providers = { solacebroker = solacebroker.solace_1 }

  vpn_name                  = "amartens-test"
  services_enabled          = false
  semp_over_msg_bus_enabled = false
}

module "solace_1_client_amartens_test" {
  source    = "./modules/client"
  providers = { solacebroker = solacebroker.solace_1 }

  vpn_name        = module.solace_1_vpn_amartens_test.vpn_name
  client_username = "default"
  client_password = var.default_client_password
}

# --- sam VPN (Solace Agent Mesh) ---

module "solace_1_vpn_sam" {
  source    = "./modules/vpn"
  providers = { solacebroker = solacebroker.solace_1 }

  vpn_name                  = "sam"
  services_enabled          = false
  semp_over_msg_bus_enabled = false
}

module "solace_1_client_sam" {
  source    = "./modules/client"
  providers = { solacebroker = solacebroker.solace_1 }

  vpn_name        = module.solace_1_vpn_sam.vpn_name
  client_username = "default"
  client_password = var.default_client_password
}

# --- Telemetry (on default VPN) ---

module "solace_1_telemetry" {
  source    = "./modules/telemetry"
  providers = { solacebroker = solacebroker.solace_1 }

  vpn_name       = module.solace_1_vpn_default.vpn_name
  trace_password = var.trace_password
}
