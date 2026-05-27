output "workers_dev_url" {
  description = "Expected workers.dev URL when enable_workers_dev is true."
  value = (
    var.enable_workers_dev
    ? "https://${cloudflare_worker.archive_proxy.name}.${var.workers_dev_subdomain}.workers.dev"
    : null
  )
}

output "custom_domain_url" {
  description = "Custom Worker URL when custom_domain_hostname is set."
  value       = var.custom_domain_hostname == null ? null : "https://${var.custom_domain_hostname}"
}

output "worker_name" {
  description = "Deployed Worker name."
  value       = cloudflare_worker.archive_proxy.name
}
