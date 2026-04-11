terraform {
  required_providers {
    solacebroker = {
      source = "registry.terraform.io/solaceproducts/solacebroker"
    }
  }
}

# --- Telemetry Profile ---

resource "solacebroker_msg_vpn_telemetry_profile" "this" {
  msg_vpn_name           = var.vpn_name
  telemetry_profile_name = var.telemetry_profile_name
  trace_enabled          = true
  receiver_enabled       = true

  receiver_acl_connect_default_action                          = "allow"
  receiver_max_connection_count_per_client_username             = 1000
  receiver_event_connection_count_per_client_username_threshold = { "clear_percent" : 60, "set_percent" : 80 }
  queue_event_bind_count_threshold                              = { "clear_percent" : 60, "set_percent" : 80 }
  queue_event_msg_spool_usage_threshold                         = { "clear_percent" : 1, "set_percent" : 2 }
}

# --- Trace Filter ---

resource "solacebroker_msg_vpn_telemetry_profile_trace_filter" "this" {
  msg_vpn_name           = var.vpn_name
  telemetry_profile_name = solacebroker_msg_vpn_telemetry_profile.this.telemetry_profile_name
  trace_filter_name      = ">"
  enabled                = true
}

# --- Trace Filter Subscription (match all topics) ---

resource "solacebroker_msg_vpn_telemetry_profile_trace_filter_subscription" "this" {
  msg_vpn_name           = var.vpn_name
  telemetry_profile_name = solacebroker_msg_vpn_telemetry_profile_trace_filter.this.telemetry_profile_name
  trace_filter_name      = solacebroker_msg_vpn_telemetry_profile_trace_filter.this.trace_filter_name
  subscription           = ">"
  subscription_syntax    = "smf"
}

# --- Trace Client Username ---

resource "solacebroker_msg_vpn_client_username" "trace" {
  client_username     = "trace"
  password            = var.trace_password
  enabled             = true
  msg_vpn_name        = var.vpn_name
  acl_profile_name    = "#telemetry-${var.telemetry_profile_name}"
  client_profile_name = "#telemetry-${var.telemetry_profile_name}"

  depends_on = [solacebroker_msg_vpn_telemetry_profile.this]
}
