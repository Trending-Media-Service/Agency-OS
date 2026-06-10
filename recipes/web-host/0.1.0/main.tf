variable "domain" { type = string }
variable "region" { type = string; default = "asia-south1" }
variable "image" { type = string; default = "gcr.io/cloudrun/hello" } # default to hello world
variable "project_id" { type = string } # Target project ID from brand-baseline
variable "tier" { type = string; default = "shared" }

# Create Cloud Run service
resource "google_cloud_run_v2_service" "web" {
  name     = "web-service"
  location = var.region
  project  = var.project_id

  template {
    containers {
      image = var.image
      ports {
        container_port = 8080
      }
    }
  }
}

# Make Cloud Run service public
resource "google_cloud_run_v2_service_iam_member" "public" {
  project  = var.project_id
  location = google_cloud_run_v2_service.web.location
  name     = google_cloud_run_v2_service.web.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Domain mapping for custom domain
resource "google_cloud_run_domain_mapping" "mapping" {
  name     = var.domain
  location = var.region
  project  = var.project_id

  metadata {
    namespace = var.project_id
  }

  spec {
    route_name = google_cloud_run_v2_service.web.name
  }
}

# Outputs
output "service_url" {
  value = google_cloud_run_v2_service.web.uri
}

output "dns_zone" {
  value = "dns-zone-for-${var.domain}"
}

output "cert_id" {
  value = "ssl-cert-for-${var.domain}"
}
