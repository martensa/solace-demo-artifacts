output "cluster_name" {
  description = "The name of the DMR cluster"
  value       = solacebroker_dmr_cluster.this.dmr_cluster_name
}

output "link_enabled" {
  description = "Whether the DMR cluster link is enabled"
  value       = solacebroker_dmr_cluster_link.this.enabled
}
