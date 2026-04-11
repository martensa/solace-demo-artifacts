# =============================================================================
# Outputs
# =============================================================================

output "solace_1_vpns" {
  description = "VPN names created on solace-1"
  value = [
    module.solace_1_vpn_default.vpn_name,
    module.solace_1_vpn_amartens_test.vpn_name,
    module.solace_1_vpn_sam.vpn_name,
  ]
}

output "solace_2_vpns" {
  description = "VPN names created on solace-2"
  value = [
    module.solace_2_vpn_default.vpn_name,
    module.solace_2_vpn_amartens_test.vpn_name,
  ]
}

output "dmr_solace_1_cluster" {
  description = "DMR cluster name on solace-1"
  value       = module.solace_1_dmr.cluster_name
}

output "dmr_solace_2_cluster" {
  description = "DMR cluster name on solace-2"
  value       = module.solace_2_dmr.cluster_name
}

output "dmr_links_enabled" {
  description = "Whether DMR links are currently active"
  value       = var.dmr_enabled
}
