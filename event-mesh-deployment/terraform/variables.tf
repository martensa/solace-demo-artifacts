# -----------------------------------------------------------------------------
# Broker connection — solace-1
# -----------------------------------------------------------------------------

variable "solace_1_url" {
  description = "SEMP management URL for solace-1"
  type        = string
}

variable "solace_1_username" {
  description = "Admin username for solace-1 SEMP access"
  type        = string
}

variable "solace_1_password" {
  description = "Admin password for solace-1 SEMP access"
  type        = string
  sensitive   = true
}

# -----------------------------------------------------------------------------
# Broker connection — solace-2
# -----------------------------------------------------------------------------

variable "solace_2_url" {
  description = "SEMP management URL for solace-2"
  type        = string
}

variable "solace_2_username" {
  description = "Admin username for solace-2 SEMP access"
  type        = string
}

variable "solace_2_password" {
  description = "Admin password for solace-2 SEMP access"
  type        = string
  sensitive   = true
}

# -----------------------------------------------------------------------------
# Client credentials
# -----------------------------------------------------------------------------

variable "default_client_password" {
  description = "Password for the 'default' client username on all VPNs"
  type        = string
  sensitive   = true
}

variable "trace_password" {
  description = "Password for the 'trace' telemetry client username"
  type        = string
  sensitive   = true
}

# -----------------------------------------------------------------------------
# DMR
# -----------------------------------------------------------------------------

variable "dmr_password" {
  description = "Authentication password for DMR cluster links"
  type        = string
  sensitive   = true
}

variable "dmr_enabled" {
  description = "Enable the DMR cluster links between brokers"
  type        = bool
  default     = false
}
