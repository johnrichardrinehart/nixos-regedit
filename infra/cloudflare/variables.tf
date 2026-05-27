variable "cloudflare_account_id" {
  description = "Cloudflare account ID that owns the Worker."
  type        = string
}

variable "cloudflare_zone_id" {
  description = "Optional zone ID for a custom Worker domain."
  type        = string
  default     = null
}

variable "cloudflare_zone_name" {
  description = "Optional zone name for a custom Worker domain."
  type        = string
  default     = null
}

variable "worker_name" {
  description = "Cloudflare Worker script name."
  type        = string
  default     = "nixos-regedit-archive-proxy"
}

variable "worker_version_tag" {
  description = "Human-readable tag attached to the Worker version."
  type        = string
  default     = "nixos-regedit"
}

variable "compatibility_date" {
  description = "Cloudflare Workers compatibility date."
  type        = string
  default     = "2026-05-27"
}

variable "workers_dev_subdomain" {
  description = "Account workers.dev subdomain, used only to print the expected default proxy URL."
  type        = string
  default     = "johnrichardrinehart"
}

variable "enable_workers_dev" {
  description = "Expose the Worker at worker_name.workers_dev_subdomain.workers.dev."
  type        = bool
  default     = true
}

variable "app_url" {
  description = "URL to redirect the Worker root to."
  type        = string
  default     = "https://johnrichardrinehart.github.io/nixos-regedit/"
}

variable "custom_domain_hostname" {
  description = "Optional custom hostname to route directly to the Worker."
  type        = string
  default     = null
}

variable "allowed_origins" {
  description = "Origins allowed to call the proxy. Include \"null\" for local file:// standalone testing."
  type        = list(string)
  default = [
    "https://johnrichardrinehart.github.io",
    "null",
  ]
}

variable "max_response_bytes" {
  description = "Maximum upstream archive size the Worker will stream."
  type        = number
  default     = 536870912
}

variable "cache_ttl_seconds" {
  description = "Cache TTL for unauthenticated successful archive responses."
  type        = number
  default     = 86400
}

variable "rate_limit_namespace_id" {
  description = "Account-unique positive integer string for the Worker rate-limit binding."
  type        = string
  default     = "1001"
}

variable "rate_limit_requests_per_period" {
  description = "Requests allowed per client key in each Cloudflare location."
  type        = number
  default     = 60
}

variable "rate_limit_period_seconds" {
  description = "Rate-limit window in seconds. Cloudflare supports 10 or 60."
  type        = number
  default     = 60

  validation {
    condition     = contains([10, 60], var.rate_limit_period_seconds)
    error_message = "Cloudflare Worker rate-limit periods must be 10 or 60 seconds."
  }
}
