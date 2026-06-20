terraform {
  required_version = ">= 1.0.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.8"
    }
  }
}

provider "google" {
  region = var.region
}

variable "custom_domain" {
  type    = string
  default = ""
}

variable "region" {
  type    = string
  default = "asia-south1"
}

variable "image" {
  type    = string
  default = "gcr.io/cloudrun/hello" # default to hello world
}

variable "project_id" {
  type = string
}

# Create Cloud Run service
resource "google_cloud_run_v2_service" "web" {
  name                 = "web-service"
  location             = var.region
  project              = var.project_id
  invoker_iam_disabled = true # Disables IAM invoker check, enabling public storefront access safely under Domain Restricted Sharing policies

  template {
    containers {
      image = var.image
      ports {
        container_port = 8080
      }
    }
  }
}

# Global HTTP(S) Load Balancer for Custom Domain Mapping
# (only created if var.custom_domain is not empty)

resource "google_compute_global_address" "lb_ip" {
  count   = var.custom_domain != "" ? 1 : 0
  name    = "web-lb-ip"
  project = var.project_id
}

resource "google_compute_region_network_endpoint_group" "serverless_neg" {
  count                 = var.custom_domain != "" ? 1 : 0
  name                  = "web-serverless-neg"
  network_endpoint_type = "SERVERLESS"
  region                = var.region
  project               = var.project_id

  cloud_run {
    service = google_cloud_run_v2_service.web.name
  }
}

# Value-Add ONS: Google Cloud Armor WAF Policy
resource "google_compute_security_policy" "waf_policy" {
  count       = var.custom_domain != "" ? 1 : 0
  name        = "web-waf-policy"
  project     = var.project_id
  description = "OWASP Top 10 and DDoS defense policy for brand storefront"

  # Preconfigured rule for SQL Injection
  rule {
    action   = "deny(403)"
    priority = "1000"
    match {
      expr {
        expression = "evaluatePreconfiguredExpr('sqli-v33-stable')"
      }
    }
    description = "Deny SQL injection attempts"
  }

  # Preconfigured rule for Cross-Site Scripting (XSS)
  rule {
    action   = "deny(403)"
    priority = "1001"
    match {
      expr {
        expression = "evaluatePreconfiguredExpr('xss-v33-stable')"
      }
    }
    description = "Deny XSS attempts"
  }

  # Default rule: Allow all other traffic
  rule {
    action   = "allow"
    priority = "2147483647"
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    description = "Default rule"
  }
}

resource "google_compute_backend_service" "backend" {
  count                 = var.custom_domain != "" ? 1 : 0
  name                  = "web-backend"
  project               = var.project_id
  load_balancing_scheme = "EXTERNAL_MANAGED"

  backend {
    group = google_compute_region_network_endpoint_group.serverless_neg[0].id
  }

  # Value-Add ONS: Cloud CDN Edge Caching
  enable_cdn = true
  cdn_policy {
    cache_mode        = "CACHE_ALL_STATIC"
    client_ttl        = 3600
    default_ttl       = 3600
    max_ttl           = 86400
    serve_while_stale = 86400
  }

  # Value-Add ONS: Bind WAF Policy
  security_policy = google_compute_security_policy.waf_policy[0].id
}

resource "google_compute_url_map" "url_map" {
  count           = var.custom_domain != "" ? 1 : 0
  name            = "web-url-map"
  project         = var.project_id
  default_service = google_compute_backend_service.backend[0].id
}

resource "google_compute_managed_ssl_certificate" "ssl_cert" {
  count   = var.custom_domain != "" ? 1 : 0
  name    = "web-ssl-cert"
  project = var.project_id

  managed {
    domains = [var.custom_domain]
  }
}

resource "google_compute_target_https_proxy" "https_proxy" {
  count            = var.custom_domain != "" ? 1 : 0
  name             = "web-https-proxy"
  project          = var.project_id
  url_map          = google_compute_url_map.url_map[0].id
  ssl_certificates = [google_compute_managed_ssl_certificate.ssl_cert[0].id]
}

resource "google_compute_global_forwarding_rule" "forwarding_rule" {
  count                 = var.custom_domain != "" ? 1 : 0
  name                  = "web-forwarding-rule"
  project               = var.project_id
  target                = google_compute_target_https_proxy.https_proxy[0].id
  port_range            = "443"
  ip_address            = google_compute_global_address.lb_ip[0].address
  load_balancing_scheme = "EXTERNAL_MANAGED"
}

# Value-Add ONS: Automated Cloud DNS Zone SSL Verification
resource "google_dns_managed_zone" "brand_dns" {
  count       = var.custom_domain != "" ? 1 : 0
  name        = "web-dns-zone"
  dns_name    = "${var.custom_domain}."
  description = "Automated DNS zone for brand custom domain validation"
  project     = var.project_id
}

# A Record pointing to the Load Balancer IP
resource "google_dns_record_set" "a_record" {
  count        = var.custom_domain != "" ? 1 : 0
  name         = google_dns_managed_zone.brand_dns[0].dns_name
  managed_zone = google_dns_managed_zone.brand_dns[0].name
  type         = "A"
  ttl          = 300
  project      = var.project_id
  rrdatas      = [google_compute_global_address.lb_ip[0].address]
}

# CAA Record permitting Let's Encrypt and Google Trust Services to issue certificates
resource "google_dns_record_set" "caa_record" {
  count        = var.custom_domain != "" ? 1 : 0
  name         = google_dns_managed_zone.brand_dns[0].dns_name
  managed_zone = google_dns_managed_zone.brand_dns[0].name
  type         = "CAA"
  ttl          = 300
  project      = var.project_id
  rrdatas      = [
    "0 issue \"pki.goog\"",
    "0 issue \"letsencrypt.org\""
  ]
}

# Outputs
output "service_url" {
  value = google_cloud_run_v2_service.web.uri
}

output "lb_ip" {
  value = var.custom_domain != "" ? google_compute_global_address.lb_ip[0].address : ""
}

# Value-Add ONS: Output the delegated Name Servers for domain setup
output "dns_zone_name_servers" {
  value = var.custom_domain != "" ? google_dns_managed_zone.brand_dns[0].name_servers : []
}

