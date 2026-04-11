variable "vpn_name" {
  description = "Name of the Message VPN"
  type        = string
}

variable "queue_name" {
  description = "Name of the queue"
  type        = string
}

variable "access_type" {
  description = "Queue access type: 'exclusive' or 'non-exclusive'"
  type        = string
  default     = "non-exclusive"
}

variable "permission" {
  description = "Default queue permission"
  type        = string
  default     = "consume"
}

variable "subscriptions" {
  description = "List of topic subscriptions for the queue"
  type        = list(string)
  default     = []
}
