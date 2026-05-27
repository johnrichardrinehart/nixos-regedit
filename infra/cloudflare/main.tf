terraform {
  required_version = ">= 1.6.0"

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.19"
    }
  }
}

provider "cloudflare" {}

locals {
  worker_script = "workers/archive-proxy.js"
}

resource "cloudflare_worker" "archive_proxy" {
  account_id = var.cloudflare_account_id
  name       = var.worker_name

  subdomain = {
    enabled          = var.enable_workers_dev
    previews_enabled = false
  }
}

resource "cloudflare_worker_version" "archive_proxy" {
  account_id         = var.cloudflare_account_id
  worker_id          = cloudflare_worker.archive_proxy.id
  compatibility_date = var.compatibility_date
  main_module        = local.worker_script

  annotations = {
    workers_message = "Deploy NixOS Regedit archive proxy"
    workers_tag     = var.worker_version_tag
  }

  modules = [{
    content_file = local.worker_script
    content_type = "application/javascript+module"
    name         = local.worker_script
  }]

  bindings = [
    {
      name = "APP_URL"
      text = var.app_url
      type = "plain_text"
    },
    {
      name = "ALLOWED_ORIGINS"
      text = join(",", var.allowed_origins)
      type = "plain_text"
    },
    {
      name = "MAX_RESPONSE_BYTES"
      text = tostring(var.max_response_bytes)
      type = "plain_text"
    },
    {
      name = "CACHE_TTL_SECONDS"
      text = tostring(var.cache_ttl_seconds)
      type = "plain_text"
    },
    {
      name         = "ARCHIVE_PROXY_RATE_LIMITER"
      namespace_id = var.rate_limit_namespace_id
      type         = "ratelimit"
      simple = {
        limit  = var.rate_limit_requests_per_period
        period = var.rate_limit_period_seconds
      }
    },
  ]
}

resource "cloudflare_workers_deployment" "archive_proxy" {
  account_id  = var.cloudflare_account_id
  script_name = cloudflare_worker.archive_proxy.name
  strategy    = "percentage"

  annotations = {
    workers_message = "Deploy NixOS Regedit archive proxy"
  }

  versions = [{
    percentage = 100
    version_id = cloudflare_worker_version.archive_proxy.id
  }]
}

resource "cloudflare_workers_script_subdomain" "archive_proxy" {
  account_id       = var.cloudflare_account_id
  script_name      = cloudflare_worker.archive_proxy.name
  enabled          = var.enable_workers_dev
  previews_enabled = false

  depends_on = [cloudflare_workers_deployment.archive_proxy]
}

resource "cloudflare_workers_custom_domain" "archive_proxy" {
  count = var.custom_domain_hostname == null ? 0 : 1

  account_id = var.cloudflare_account_id
  hostname   = var.custom_domain_hostname
  service    = cloudflare_worker.archive_proxy.name
  zone_id    = var.cloudflare_zone_id
  zone_name  = var.cloudflare_zone_name

  depends_on = [cloudflare_workers_deployment.archive_proxy]
}
