variable "project_id" { type = string }
variable "region" { type = string; default = "asia-south1" }
variable "db_connection_name" { type = string }
variable "db_name" { type = string }
variable "db_user" { type = string }
variable "db_password" { type = string }
variable "image" { type = string; default = "docker.io/n8nio/n8n:latest" }

resource "google_cloud_run_v2_service" "n8n" {
  name     = "n8n-service"
  location = var.region
  project  = var.project_id

  template {
    containers {
      image = var.image
      ports {
        container_port = 5678
      }
      
      env {
        name  = "DB_TYPE"
        value = "postgresdb"
      }
      env {
        name  = "DB_POSTGRESDB_DATABASE"
        value = var.db_name
      }
      env {
        name  = "DB_POSTGRESDB_USER"
        value = var.db_user
      }
      env {
        name  = "DB_POSTGRESDB_PASSWORD"
        value = var.db_password
      }
      env {
        name  = "DB_POSTGRESDB_HOST"
        value = "/cloudsql/${var.db_connection_name}"
      }
      
      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
    }
    
    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [var.db_connection_name]
      }
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  project  = var.project_id
  location = google_cloud_run_v2_service.n8n.location
  name     = google_cloud_run_v2_service.n8n.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

output "service_url" {
  value = google_cloud_run_v2_service.n8n.uri
}
