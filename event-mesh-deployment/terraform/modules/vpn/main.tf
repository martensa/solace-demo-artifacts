terraform {
  required_providers {
    solacebroker = {
      source = "registry.terraform.io/solaceproducts/solacebroker"
    }
  }
}

# --- Message VPN ---

resource "solacebroker_msg_vpn" "this" {
  msg_vpn_name              = var.vpn_name
  authentication_basic_type = "internal"
  dmr_enabled               = var.dmr_enabled
  enabled                   = true
  jndi_enabled              = var.jndi_enabled

  # Limits
  max_connection_count                = var.max_connection_count
  max_kafka_broker_connection_count   = 300
  max_msg_spool_usage                 = var.max_msg_spool_usage
  max_subscription_count              = var.max_subscription_count
  max_transacted_session_count        = var.max_transacted_session_count
  max_transaction_count               = var.max_transaction_count
  replication_queue_max_msg_spool_usage = var.max_msg_spool_usage

  # SEMP over message bus
  semp_over_msg_bus_admin_client_enabled           = var.semp_over_msg_bus_enabled
  semp_over_msg_bus_admin_distributed_cache_enabled = var.semp_over_msg_bus_enabled
  semp_over_msg_bus_admin_enabled                   = var.semp_over_msg_bus_enabled
  semp_over_msg_bus_show_enabled                    = var.semp_over_msg_bus_enabled

  # Event thresholds
  event_connection_count_threshold                       = { "clear_percent" : 60, "set_percent" : 80 }
  event_egress_flow_count_threshold                      = { "clear_percent" : 60, "set_percent" : 80 }
  event_egress_msg_rate_threshold                        = { "clear_value" : 3000000, "set_value" : 4000000 }
  event_endpoint_count_threshold                         = { "clear_percent" : 60, "set_percent" : 80 }
  event_ingress_flow_count_threshold                     = { "clear_percent" : 60, "set_percent" : 80 }
  event_ingress_msg_rate_threshold                       = { "clear_value" : 3000000, "set_value" : 4000000 }
  event_msg_spool_usage_threshold                        = { "clear_percent" : 60, "set_percent" : 80 }
  event_service_amqp_connection_count_threshold          = { "clear_percent" : 60, "set_percent" : 80 }
  event_service_mqtt_connection_count_threshold          = { "clear_percent" : 60, "set_percent" : 80 }
  event_service_rest_incoming_connection_count_threshold = { "clear_percent" : 60, "set_percent" : 80 }
  event_service_smf_connection_count_threshold           = { "clear_percent" : 60, "set_percent" : 80 }
  event_service_web_connection_count_threshold           = { "clear_percent" : 60, "set_percent" : 80 }
  event_subscription_count_threshold                     = { "clear_percent" : 60, "set_percent" : 80 }
  event_transacted_session_count_threshold               = { "clear_percent" : 60, "set_percent" : 80 }
  event_transaction_count_threshold                      = { "clear_percent" : 60, "set_percent" : 80 }

  # AMQP (plain-text port is per-VPN on software brokers; VPNs with
  # messaging disabled can still enable AMQP selectively, e.g. the
  # sam VPN for the tracing receiver of the OTel Collector)
  service_amqp_max_connection_count      = var.max_connection_count
  service_amqp_plain_text_enabled        = coalesce(var.amqp_plain_text_enabled, var.services_enabled)
  service_amqp_plain_text_listen_port    = var.amqp_plain_text_listen_port
  service_amqp_tls_enabled               = var.services_enabled
  service_amqp_tls_listen_port           = 5671

  # MQTT
  service_mqtt_max_connection_count          = var.max_connection_count
  service_mqtt_plain_text_enabled            = var.services_enabled
  service_mqtt_plain_text_listen_port        = 1883
  service_mqtt_tls_enabled                   = var.services_enabled
  service_mqtt_tls_listen_port               = 8883
  service_mqtt_tls_web_socket_enabled        = var.services_enabled
  service_mqtt_tls_web_socket_listen_port    = 8443
  service_mqtt_web_socket_enabled            = var.services_enabled
  service_mqtt_web_socket_listen_port        = 8000

  # REST
  service_rest_incoming_max_connection_count      = var.max_connection_count
  service_rest_incoming_plain_text_enabled        = var.services_enabled
  service_rest_incoming_plain_text_listen_port    = 9000
  service_rest_incoming_tls_enabled               = var.services_enabled
  service_rest_incoming_tls_listen_port           = 9443
  service_rest_outgoing_max_connection_count      = var.max_connection_count

  # SMF & Web
  service_smf_max_connection_count = var.max_connection_count
  service_web_max_connection_count = var.max_connection_count

  lifecycle {
    prevent_destroy = true
  }
}

# --- ACL Profile ---

resource "solacebroker_msg_vpn_acl_profile" "this" {
  acl_profile_name               = "default"
  msg_vpn_name                   = solacebroker_msg_vpn.this.msg_vpn_name
  client_connect_default_action  = "allow"
  publish_topic_default_action   = "allow"
  subscribe_topic_default_action = "allow"
}

# --- Client Profile ---

resource "solacebroker_msg_vpn_client_profile" "this" {
  client_profile_name                    = "default"
  msg_vpn_name                           = solacebroker_msg_vpn.this.msg_vpn_name
  allow_bridge_connections_enabled       = true
  allow_guaranteed_endpoint_create_enabled = true
  allow_guaranteed_msg_receive_enabled   = true
  allow_guaranteed_msg_send_enabled      = true
  allow_shared_subscriptions_enabled     = true
  allow_transacted_sessions_enabled      = true
  max_connection_count_per_client_username              = var.max_connection_count
  max_subscription_count                                = var.max_subscription_count
  max_transaction_count                                 = var.max_transaction_count
  service_smf_max_connection_count_per_client_username  = var.max_connection_count
  service_web_max_connection_count_per_client_username  = var.max_connection_count

  event_client_provisioned_endpoint_spool_usage_threshold          = { "clear_percent" : 18, "set_percent" : 25 }
  event_connection_count_per_client_username_threshold              = { "clear_percent" : 60, "set_percent" : 80 }
  event_egress_flow_count_threshold                                = { "clear_percent" : 60, "set_percent" : 80 }
  event_endpoint_count_per_client_username_threshold                = { "clear_percent" : 60, "set_percent" : 80 }
  event_ingress_flow_count_threshold                               = { "clear_percent" : 60, "set_percent" : 80 }
  event_service_smf_connection_count_per_client_username_threshold  = { "clear_percent" : 60, "set_percent" : 80 }
  event_service_web_connection_count_per_client_username_threshold  = { "clear_percent" : 60, "set_percent" : 80 }
  event_subscription_count_threshold                               = { "clear_percent" : 60, "set_percent" : 80 }
  event_transacted_session_count_threshold                         = { "clear_percent" : 60, "set_percent" : 80 }
  event_transaction_count_threshold                                = { "clear_percent" : 60, "set_percent" : 80 }
}
