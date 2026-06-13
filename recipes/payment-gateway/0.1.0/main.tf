variable "project_id" { type = string }
variable "provider" { type = string; default = "stripe" }
variable "webhook_url" { type = string }

resource "random_id" "webhook_id" {
  byte_length = 8
}

resource "google_secret_manager_secret" "webhook_secret" {
  secret_id = "payment-${var.provider}-webhook-signing-key"
  project   = var.project_id
  replication {
    auto {}
  }
}

output "webhook_id" {
  value = "wh_${random_id.webhook_id.hex}"
}

output "webhook_secret_ref" {
  value = google_secret_manager_secret.webhook_secret.id
}

output "status" {
  value = "active"
}
