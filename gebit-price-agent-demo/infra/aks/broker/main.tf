# =============================================================================
# AKS event broker: Message VPNs and client usernames (AKS-MIGRATION-PLAN.md
# A13). Same VPN layout as the lab broker solace-1, without DMR, telemetry,
# the lab-only Event Portal VPN or SEMP over the message bus.
#
# Run only through the aks.sh helper, which feeds the four passwords from
# Key Vault as TF_VAR_* and never puts them on screen:
#
#   kaks -n solace port-forward svc/solace-pubsubplus 18080:8080   # open
#   tfa init && tfa plan && tfa apply
#
# SEMP goes to 127.0.0.1:18080 only. Port 8080 on the Mac is the LAB broker
# solace-1: never point this root at it. State stays local in this
# directory (gitignored: *.tfstate, .terraform/, .terraform.lock.hcl) and
# holds the client passwords.
#
# Default objects: on a fresh broker the VPN "default" and, in every VPN,
# the client username "default" plus the ACL and client profiles "default"
# already exist. The provider creates these resources with SEMP PUT
# (create-or-replace), so the first apply takes them over without an
# import block, exactly as the lab root does on fresh brokers; a destroy
# only drops them from state. Import blocks would even break the first
# plan, because the VPN "sam" (and with it its "default" client username)
# does not exist before the apply.
# =============================================================================

terraform {
  required_version = ">= 1.5"

  required_providers {
    solacebroker = {
      source  = "registry.terraform.io/solaceproducts/solacebroker"
      version = "= 1.3.0"
    }
  }
}

# -----------------------------------------------------------------------------
# Passwords (sensitive, no defaults; set by tfa from Key Vault)
# -----------------------------------------------------------------------------

variable "semp_password" {
  description = "SEMP admin password of the AKS broker (Key Vault solace-admin)"
  type        = string
  sensitive   = true
  nullable    = false

  validation {
    condition     = length(var.semp_password) > 0
    error_message = "semp_password is empty (TF_VAR_semp_password from Key Vault solace-admin)."
  }
}

variable "sam_password" {
  description = "Password of client username sam in VPN sam (Key Vault solace-sam)"
  type        = string
  sensitive   = true
  nullable    = false

  validation {
    condition     = length(var.sam_password) > 0
    error_message = "sam_password is empty (TF_VAR_sam_password from Key Vault solace-sam)."
  }
}

variable "gpos_password" {
  description = "Password of client username gpos in VPN default (Key Vault solace-gpos)"
  type        = string
  sensitive   = true
  nullable    = false

  validation {
    condition     = length(var.gpos_password) > 0
    error_message = "gpos_password is empty (TF_VAR_gpos_password from Key Vault solace-gpos)."
  }
}

variable "default_password" {
  description = "Password of the disabled client username default in both VPNs (Key Vault solace-default-off)"
  type        = string
  sensitive   = true
  nullable    = false

  validation {
    condition     = length(var.default_password) > 0
    error_message = "default_password is empty (TF_VAR_default_password from Key Vault solace-default-off)."
  }
}

# -----------------------------------------------------------------------------
# Provider: the port-forward to the AKS broker, nothing else
# -----------------------------------------------------------------------------

provider "solacebroker" {
  alias    = "aks"
  url      = "http://127.0.0.1:18080"
  username = "admin"
  password = var.semp_password
}

# -----------------------------------------------------------------------------
# VPNs (modules shared with event-mesh-deployment/terraform)
# -----------------------------------------------------------------------------

# default: all messaging services on (gpos-demo connects here as client
# username gpos). Unlike the lab, SEMP over the message bus stays off:
# nothing on AKS uses it (tfa and the scripts use SEMP over HTTP on the
# port-forward), and the gpos password lives in internet-facing pods.
module "vpn_default" {
  source    = "../../../../event-mesh-deployment/terraform/modules/vpn"
  providers = { solacebroker = solacebroker.aks }

  vpn_name                  = "default"
  dmr_enabled               = false
  services_enabled          = true
  semp_over_msg_bus_enabled = false
}

# sam: Solace Agent Mesh. AMQP, MQTT and REST off, SEMP over the message
# bus off; SMF and Web (ws://...:8008, used by SAM) stay enabled. Unlike
# the lab, no AMQP listener on 5673 (no OTel broker tracing on AKS).
module "vpn_sam" {
  source    = "../../../../event-mesh-deployment/terraform/modules/vpn"
  providers = { solacebroker = solacebroker.aks }

  vpn_name                  = "sam"
  dmr_enabled               = false
  services_enabled          = false
  semp_over_msg_bus_enabled = false
}

# -----------------------------------------------------------------------------
# Client usernames
# -----------------------------------------------------------------------------

module "client_sam" {
  source    = "../../../../event-mesh-deployment/terraform/modules/client"
  providers = { solacebroker = solacebroker.aks }

  vpn_name        = module.vpn_sam.vpn_name
  client_username = "sam"
  client_password = var.sam_password
}

module "client_gpos" {
  source    = "../../../../event-mesh-deployment/terraform/modules/client"
  providers = { solacebroker = solacebroker.aks }

  vpn_name        = module.vpn_default.vpn_name
  client_username = "gpos"
  client_password = var.gpos_password
}

# The built-in client username "default" exists in every VPN; disabled in
# both, with a generated password, so nobody logs in anonymously.
module "client_default_off_default" {
  source    = "../../../../event-mesh-deployment/terraform/modules/client"
  providers = { solacebroker = solacebroker.aks }

  vpn_name        = module.vpn_default.vpn_name
  client_username = "default"
  client_password = var.default_password
  enabled         = false
}

module "client_default_off_sam" {
  source    = "../../../../event-mesh-deployment/terraform/modules/client"
  providers = { solacebroker = solacebroker.aks }

  vpn_name        = module.vpn_sam.vpn_name
  client_username = "default"
  client_password = var.default_password
  enabled         = false
}

# -----------------------------------------------------------------------------
# Outputs (names only, no secrets)
# -----------------------------------------------------------------------------

output "vpns" {
  description = "Message VPNs managed on the AKS broker"
  value       = [module.vpn_default.vpn_name, module.vpn_sam.vpn_name]
}

output "client_usernames" {
  description = "Enabled client usernames as vpn/username"
  value = [
    "${module.vpn_sam.vpn_name}/${module.client_sam.client_username}",
    "${module.vpn_default.vpn_name}/${module.client_gpos.client_username}",
  ]
}
