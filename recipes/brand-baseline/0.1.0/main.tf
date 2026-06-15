variable "brand_id" { type = string }
variable "tenant_id" { type = string }
variable "custom_project_id" {
  type    = string
  default = ""
}

locals {
  is_dedicated = var.tier == "dedicated"
  use_custom   = var.custom_project_id != ""
  project_id   = local.use_custom ? var.custom_project_id : (local.is_dedicated ? google_project.brand_project[0].project_id : "aos-shared-tier")
}
variable "tier" {
  type    = string
  default = "shared"
}
variable "region" {
  type    = string
  default = "asia-south1"
}
variable "budget_amount" {
  type    = number
  default = 1000
}
variable "billing_account" {
  type    = string
  default = ""
}
variable "folder_id" {
  type    = string
  default = ""
}
variable "shared_postgres_instance" {
  type    = string
  default = "aos-shared-postgres"
}

# Random password for database user
resource "random_password" "db_password" {
  count   = var.tier == "shared" ? 1 : 0
  length  = 16
  special = false
}

# Dedicated project creation
resource "random_id" "project_suffix" {
  count       = (var.tier == "dedicated" && var.custom_project_id == "") ? 1 : 0
  byte_length = 4
}

resource "google_project" "brand_project" {
  count           = (var.tier == "dedicated" && var.custom_project_id == "") ? 1 : 0
  name            = "brand-${var.brand_id}"
  project_id      = "aos-${var.brand_id}-${random_id.project_suffix[0].hex}"
  folder_id       = var.folder_id != "" ? var.folder_id : null
  billing_account = var.billing_account != "" ? var.billing_account : null
}

# Enable APIs for dedicated project
resource "google_project_service" "services" {
  for_each = var.tier == "dedicated" ? toset([
    "run.googleapis.com",
    "dns.googleapis.com",
    "secretmanager.googleapis.com",
    "sqladmin.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com"
  ]) : []
  project = local.project_id
  service = each.key
}

# Dedicated Service Account
resource "google_service_account" "dedicated_sa" {
  count        = var.tier == "dedicated" ? 1 : 0
  account_id   = "aos-deployer-${var.brand_id}"
  display_name = "AOS Deployer for Brand ${var.brand_id}"
  project      = local.project_id
}

# IAM roles for the service account at the project level
resource "google_project_iam_member" "dedicated_sa_roles" {
  for_each = var.tier == "dedicated" ? toset([
    "roles/run.admin",
    "roles/cloudsql.client",
    "roles/secretmanager.secretAccessor",
    "roles/logging.logWriter",
    "roles/storage.admin"
  ]) : []
  project = local.project_id
  role    = each.key
  member  = "serviceAccount:${google_service_account.dedicated_sa[0].email}"
}

# Budget guard
resource "google_billing_budget" "budget_guard" {
  count           = (var.tier == "dedicated" && var.billing_account != "" && var.custom_project_id == "") ? 1 : 0
  billing_account = var.billing_account
  display_name    = "brand-${var.brand_id}-tmg-guard"

  budget_filter {
    projects = ["projects/${local.project_id}"]
  }

  amount {
    specified_amount {
      currency_code = "INR"
      units         = tostring(var.budget_amount)
    }
  }

  threshold_rules {
    threshold_percent = 0.5
    spend_basis       = "CURRENT_SPEND"
  }
  threshold_rules {
    threshold_percent = 0.9
    spend_basis       = "CURRENT_SPEND"
  }
  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "CURRENT_SPEND"
  }
}

# Shared database & user inside the central shared instance
resource "google_sql_database" "shared_db" {
  count    = var.tier == "shared" ? 1 : 0
  name     = "db-${var.brand_id}"
  instance = var.shared_postgres_instance
  project  = "aos-shared-tier"
}

resource "google_sql_user" "shared_user" {
  count    = var.tier == "shared" ? 1 : 0
  name     = "user-${var.brand_id}"
  instance = var.shared_postgres_instance
  project  = "aos-shared-tier"
  password = random_password.db_password[0].result
}



# Output variables mapping to recipe outputs
output "project_id" {
  value = local.project_id
}

output "service_account_email" {
  value = var.tier == "dedicated" ? google_service_account.dedicated_sa[0].email : "shared-sa@aos-shared-tier.iam.gserviceaccount.com"
}

output "db_connection_name" {
  value = var.tier == "dedicated" ? "" : "aos-shared-tier:${var.region}:${var.shared_postgres_instance}"
}
