# =============================================================================
# Solace-2: VPNs, clients, telemetry, queues
# =============================================================================

# --- default VPN (all services enabled) ---

module "solace_2_vpn_default" {
  source    = "./modules/vpn"
  providers = { solacebroker = solacebroker.solace_2 }

  vpn_name                  = "default"
  services_enabled          = true
  semp_over_msg_bus_enabled = true
}

module "solace_2_client_default" {
  source    = "./modules/client"
  providers = { solacebroker = solacebroker.solace_2 }

  vpn_name        = module.solace_2_vpn_default.vpn_name
  client_username = "default"
  client_password = var.default_client_password
}

# --- amartens-test VPN (Event Portal environment for AMARTENS EVENT MESH) ---

module "solace_2_vpn_amartens_test" {
  source    = "./modules/vpn"
  providers = { solacebroker = solacebroker.solace_2 }

  vpn_name                  = "amartens-test"
  services_enabled          = false
  semp_over_msg_bus_enabled = false
}

module "solace_2_client_amartens_test" {
  source    = "./modules/client"
  providers = { solacebroker = solacebroker.solace_2 }

  vpn_name        = module.solace_2_vpn_amartens_test.vpn_name
  client_username = "default"
  client_password = var.default_client_password
}

# --- Telemetry (on default VPN) ---

module "solace_2_telemetry" {
  source    = "./modules/telemetry"
  providers = { solacebroker = solacebroker.solace_2 }

  vpn_name       = module.solace_2_vpn_default.vpn_name
  trace_password = var.trace_password
}

# --- Queue "q" (on default VPN) ---

module "solace_2_queue_q" {
  source    = "./modules/queue"
  providers = { solacebroker = solacebroker.solace_2 }

  vpn_name      = module.solace_2_vpn_default.vpn_name
  queue_name    = "q"
  subscriptions = [">"]
}
