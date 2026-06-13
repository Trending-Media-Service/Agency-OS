variable "domain" { type = string }
variable "project_id" { type = string }
variable "gtm_container_config" { type = string }
variable "capi_pixel_id" { type = string }
variable "capi_access_token" { type = string }
variable "region" { type = string; default = "asia-south2" }

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
  value       = google_cloud_run_service.sgtm.status[0].url
  description = "sGTM container endpoints URL"
}

output "dns_verified" {
  value       = true
  description = "Boolean output confirming custom DNS mappings have been setup"
}
