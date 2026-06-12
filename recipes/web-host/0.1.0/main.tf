terraform {
  required_version = ">= 1.0.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
  backend "gcs" {
    bucket = "aos-tfstate-tmg"
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

# Optional Global HTTP(S) Load Balancer for Custom Domain Mapping
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

resource "google_compute_backend_service" "backend" {
  count                 = var.custom_domain != "" ? 1 : 0
  name                  = "web-backend"
  project               = var.project_id
  load_balancing_scheme = "EXTERNAL_MANAGED"

  backend {
    group = google_compute_region_network_endpoint_group.serverless_neg[0].id
  }
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

# Outputs
output "service_url" {
  value = google_cloud_run_v2_service.web.uri
}

output "lb_ip" {
  value = var.custom_domain != "" ? google_compute_global_address.lb_ip[0].address : ""
}
