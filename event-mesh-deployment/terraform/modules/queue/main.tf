terraform {
  required_providers {
    solacebroker = {
      source = "registry.terraform.io/solaceproducts/solacebroker"
    }
  }
}

# --- Queue ---

resource "solacebroker_msg_vpn_queue" "this" {
  msg_vpn_name   = var.vpn_name
  queue_name     = var.queue_name
  access_type    = var.access_type
  permission     = var.permission
  ingress_enabled = true
  egress_enabled  = true

  event_bind_count_threshold                    = { "clear_percent" : 60, "set_percent" : 80 }
  event_msg_spool_usage_threshold               = { "clear_percent" : 18, "set_percent" : 25 }
  event_reject_low_priority_msg_limit_threshold = { "clear_percent" : 60, "set_percent" : 80 }

  lifecycle {
    prevent_destroy = true
  }
}

# --- Queue Subscriptions ---

resource "solacebroker_msg_vpn_queue_subscription" "this" {
  for_each = toset(var.subscriptions)

  msg_vpn_name       = var.vpn_name
  queue_name         = solacebroker_msg_vpn_queue.this.queue_name
  subscription_topic = each.value
}
