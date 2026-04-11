variable "cluster_name" {
  description = "Name of the DMR cluster"
  type        = string
}

variable "cluster_password" {
  description = "Authentication password for the DMR cluster"
  type        = string
  sensitive   = true
}

variable "remote_node" {
  description = "Name of the remote node"
  type        = string
}

variable "remote_address" {
  description = "Remote address (host:port) for the DMR link. Only needed when initiator = local."
  type        = string
  default     = ""
}

variable "initiator" {
  description = "Which side initiates the DMR link: 'local' or 'remote'"
  type        = string

  validation {
    condition     = contains(["local", "remote"], var.initiator)
    error_message = "Initiator must be 'local' or 'remote'."
  }
}

variable "enabled" {
  description = "Whether the DMR cluster link is enabled"
  type        = bool
  default     = false
}

variable "bridge_vpn_pairs" {
  description = "List of VPN pairs to bridge across the DMR link"
  type = list(object({
    local_vpn  = string
    remote_vpn = string
  }))
}
