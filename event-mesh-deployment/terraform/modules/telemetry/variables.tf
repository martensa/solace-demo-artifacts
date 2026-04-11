variable "vpn_name" {
  description = "Name of the Message VPN to attach telemetry to"
  type        = string
}

variable "trace_password" {
  description = "Password for the trace client username"
  type        = string
  sensitive   = true
}

variable "telemetry_profile_name" {
  description = "Name of the telemetry profile"
  type        = string
  default     = "trace"
}
