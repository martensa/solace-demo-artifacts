output "vpn_name" {
  description = "The name of the created Message VPN"
  value       = solacebroker_msg_vpn.this.msg_vpn_name
}
