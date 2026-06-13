variable "project_id" { type = string }
variable "brand_id" { type = string }
variable "tenant_id" { type = string }
variable "region" { type = string; default = "asia-south2" }
variable "db_tier" { type = string; default = "db-f1-micro" }
variable "api_service" { type = string; default = "wellness-foods" }
variable "frontend_service" { type = string; default = "tanmatra" }
variable "repo_url" { type = string; default = "https://github.com/chan8822/Wellness-Foods.git" }

locals {
  db_instance_name = "brand-${var.brand_id}-db"
  db_name          = "brand_${var.brand_id}"
  db_user          = "brand_${var.brand_id}_user"
  repo_name        = "wellness"
}

resource "random_password" "db_password" {
  length  = 16
  special = false
}

resource "random_password" "session_secret" {
  length  = 32
  special = false
}

resource "random_password" "admin_session_secret" {
  length  = 32
  special = false
}

# Cloud SQL instance
resource "google_sql_database_instance" "postgres" {
  name             = local.db_instance_name
  database_version = "POSTGRES_15"
  region           = var.region
  project          = var.project_id
  settings {
    tier = var.db_tier
  }
  deletion_protection = false
}

# Database
resource "google_sql_database" "db" {
  name     = local.db_name
  instance = google_sql_database_instance.postgres.name
  project  = var.project_id
}

# Database User
resource "google_sql_user" "user" {
  name     = local.db_user
  instance = google_sql_database_instance.postgres.name
  project  = var.project_id
  password = random_password.db_password.result
}

# Secrets
resource "google_secret_manager_secret" "db_url" {
  secret_id = "brand-${var.brand_id}-database-url"
  project   = var.project_id
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "db_url_version" {
  secret      = google_secret_manager_secret.db_url.id
  secret_data = "postgresql://${local.db_user}:${random_password.db_password.result}@localhost/${local.db_name}?host=/cloudsql/${var.project_id}:${var.region}:${local.db_instance_name}"
}

resource "google_secret_manager_secret" "session_sec" {
  secret_id = "brand-${var.brand_id}-session-secret"
  project   = var.project_id
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "session_sec_version" {
  secret      = google_secret_manager_secret.session_sec.id
  secret_data = random_password.session_secret.result
}

resource "google_secret_manager_secret" "admin_session_sec" {
  secret_id = "brand-${var.brand_id}-admin-session-secret"
  project   = var.project_id
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "admin_session_sec_version" {
  secret      = google_secret_manager_secret.admin_session_sec.id
  secret_data = random_password.admin_session_secret.result
}

# Docker Artifact Registry
resource "google_artifact_registry_repository" "repo" {
  location      = var.region
  repository_id = local.repo_name
  description   = "Docker registry for brand services"
  format        = "DOCKER"
  project       = var.project_id
}

# IAM Permissions for SAs to access secrets and SQL
data "google_project" "project" {
  project_id = var.project_id
}

resource "google_secret_manager_secret_iam_member" "db_url_access" {
  secret_id = google_secret_manager_secret.db_url.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com"
  project   = var.project_id
}

resource "google_secret_manager_secret_iam_member" "session_access" {
  secret_id = google_secret_manager_secret.session_sec.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com"
  project   = var.project_id
}

resource "google_secret_manager_secret_iam_member" "admin_session_access" {
  secret_id = google_secret_manager_secret.admin_session_sec.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com"
  project   = var.project_id
}

# Trigger deploy and migration script
resource "null_resource" "deploy" {
  depends_on = [
    google_sql_database.db,
    google_sql_user.user,
    google_secret_manager_secret_version.db_url_version,
    google_secret_manager_secret_version.session_sec_version,
    google_secret_manager_secret_version.admin_session_sec_version,
    google_artifact_registry_repository.repo,
    google_secret_manager_secret_iam_member.db_url_access,
    google_secret_manager_secret_iam_member.session_access,
    google_secret_manager_secret_iam_member.admin_session_access
  ]

  triggers = {
    repo_url = var.repo_url
  }

  provisioner "local-exec" {
    command = "bash ${path.module}/deploy_app.sh"
    environment = {
      PROJECT_ID        = var.project_id
      PROJECT_NUMBER    = data.google_project.project.number
      REGION            = var.region
      BRAND_ID          = var.brand_id
      DB_INSTANCE_NAME  = local.db_instance_name
      DB_NAME           = local.db_name
      DB_USER           = local.db_user
      DB_PASSWORD       = random_password.db_password.result
      API_SERVICE       = var.api_service
      FRONTEND_SERVICE  = var.frontend_service
      REPO_URL          = var.repo_url
    }
  }
}

# Outputs
output "frontend_url" {
  value       = "https://${var.frontend_service}-${data.google_project.project.number}.${var.region}.run.app"
  description = "Frontend application url"
}

output "api_url" {
  value       = "https://${var.api_service}-${data.google_project.project.number}.${var.region}.run.app"
  description = "API application url"
}

output "db_connection_name" {
  value       = "${var.project_id}:${var.region}:${local.db_instance_name}"
  description = "Cloud SQL database connection name"
}
