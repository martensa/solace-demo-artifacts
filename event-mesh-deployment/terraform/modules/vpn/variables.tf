variable "vpn_name" {
  description = "Name of the Message VPN"
  type        = string
}

variable "dmr_enabled" {
  description = "Enable DMR on this VPN"
  type        = bool
  default     = true
}

variable "services_enabled" {
  description = "Enable all messaging services (AMQP, MQTT, REST, SMF, Web)"
  type        = bool
  default     = true
}

variable "semp_over_msg_bus_enabled" {
  description = "Enable SEMP over message bus administration"
  type        = bool
  default     = true
}

variable "jndi_enabled" {
  description = "Enable JNDI"
  type        = bool
  default     = true
}

variable "max_connection_count" {
  description = "Maximum number of client connections"
  type        = number
  default     = 1000
}

variable "max_msg_spool_usage" {
  description = "Maximum message spool usage in MB"
  type        = number
  default     = 10000
}

variable "max_subscription_count" {
  description = "Maximum number of subscriptions"
  type        = number
  default     = 500000
}

variable "max_transacted_session_count" {
  description = "Maximum number of transacted sessions"
  type        = number
  default     = 1000
}

variable "max_transaction_count" {
  description = "Maximum number of transactions"
  type        = number
  default     = 5000
}

variable "amqp_plain_text_enabled" {
  description = "Override for AMQP plain-text (null = follow services_enabled)"
  type        = bool
  default     = null
  nullable    = true
}

variable "amqp_plain_text_listen_port" {
  description = "Per-VPN AMQP plain-text listen port"
  type        = number
  default     = 5672
}
