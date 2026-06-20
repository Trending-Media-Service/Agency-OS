variable "domain" { type = string }
variable "project_id" { type = string }
variable "gtm_container_config" { type = string }
variable "capi_pixel_id" { type = string }
variable "capi_access_token" { type = string }
variable "region" { type = string; default = "us-central1" }

# 1. Deploy GTM Cloud Run Service
resource "google_cloud_run_service" "sgtm" {
  name     = "sgtm-container"
  location = var.region
  project  = var.project_id

  template {
    spec {
      containers {
        image = "gcr.io/cloud-tagging-103020/gtm-cloud-image:stable"
        env {
          name  = "CONTAINER_CONFIG"
          value = var.gtm_container_config
        }
        env {
          name  = "RUN_AS_PREVIEW_SERVER"
          value = "false"
        }
      }
    }
  }

  metadata {
    annotations = {
      "run.googleapis.com/ingress" = "all"
    }
  }
}

resource "google_cloud_run_service_iam_member" "public" {
  location = google_cloud_run_service.sgtm.location
  project  = google_cloud_run_service.sgtm.project
  service  = google_cloud_run_service.sgtm.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# 2. Create Serverless NEG (Network Endpoint Group)
resource "google_compute_region_network_endpoint_group" "sgtm_neg" {
  name                  = "sgtm-container-neg"
  project               = var.project_id
  region                = var.region
  network_endpoint_type = "SERVERLESS"
  cloud_run {
    service = google_cloud_run_service.sgtm.name
  }
}

# 3. Reserve Global Static IP
resource "google_compute_global_address" "sgtm_ip" {
  name    = "sgtm-container-ip"
  project = var.project_id
}

# 4. Google-Managed SSL Certificate
resource "google_compute_managed_ssl_certificate" "sgtm_cert" {
  name    = "sgtm-container-cert"
  project = var.project_id
  managed {
    domains = [var.domain]
  }
}

# 5. Load Balancer Backend pointing to Serverless NEG
resource "google_compute_backend_service" "sgtm_backend" {
  name                  = "sgtm-container-backend"
  project               = var.project_id
  load_balancing_scheme = "EXTERNAL_MANAGED"
  protocol              = "HTTP"
  backend {
    group = google_compute_region_network_endpoint_group.sgtm_neg.id
  }
}

# 6. URL Map (Routing)
resource "google_compute_url_map" "sgtm_urlmap" {
  name            = "sgtm-container-urlmap"
  project         = var.project_id
  default_service = google_compute_backend_service.sgtm_backend.id
}

# 7. Target HTTPS Proxy (linking SSL and URL Map)
resource "google_compute_target_https_proxy" "sgtm_https_proxy" {
  name             = "sgtm-container-https-proxy"
  project          = var.project_id
  url_map          = google_compute_url_map.sgtm_urlmap.id
  ssl_certificates = [google_compute_managed_ssl_certificate.sgtm_cert.id]
}

# 8. Global Forwarding Rule (Exposing IP on port 443)
resource "google_compute_global_forwarding_rule" "sgtm_forwarding_rule" {
  name                  = "sgtm-container-forwarding-rule"
  project               = var.project_id
  target                = google_compute_target_https_proxy.sgtm_https_proxy.id
  port_range            = "443"
  ip_address            = google_compute_global_address.sgtm_ip.address
  load_balancing_scheme = "EXTERNAL_MANAGED"
}

# Secret Stores for CAPI (existing in 0.1.0)
resource "google_secret_manager_secret" "capi_token" {
  secret_id = "fb-capi-access-token"
  project   = var.project_id
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "capi_token_val" {
  secret      = google_secret_manager_secret.capi_token.id
  secret_data = var.capi_access_token
}

resource "google_secret_manager_secret" "capi_pixel" {
  secret_id = "fb-capi-pixel-id"
  project   = var.project_id
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "capi_pixel_val" {
  secret      = google_secret_manager_secret.capi_pixel.id
  secret_data = var.capi_pixel_id
}

output "sgtm_url" {
  value       = "https://${var.domain}"
  description = "The first-party GTM gateway URL."
}

output "static_ip_address" {
  value       = google_compute_global_address.sgtm_ip.address
  description = "Public IP to point DNS A record to."
}
