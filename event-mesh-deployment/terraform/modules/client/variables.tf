variable "vpn_name" {
  description = "Name of the Message VPN"
  type        = string
}

variable "client_username" {
  description = "Client username to create"
  type        = string
}

variable "client_password" {
  description = "Password for the client username"
  type        = string
  sensitive   = true
}

variable "acl_profile_name" {
  description = "ACL profile to assign to this client"
  type        = string
  default     = "default"
}

variable "client_profile_name" {
  description = "Client profile to assign to this client"
  type        = string
  default     = "default"
}

variable "enabled" {
  description = "Whether the client username is enabled"
  type        = bool
  default     = true
}
