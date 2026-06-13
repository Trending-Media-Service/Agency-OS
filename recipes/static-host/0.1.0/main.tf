variable "domain" { type = string }
variable "project_id" { type = string }
variable "bucket_name" { type = string }
variable "region" { type = string; default = "asia-south2" }

resource "google_storage_bucket" "static_bucket" {
  name          = var.bucket_name
  location      = var.region
  project       = var.project_id
  force_destroy = true

  website {
    main_page_suffix = "index.html"
    not_found_page   = "404.html"
  }
}

resource "google_storage_bucket_iam_member" "public_read" {
  bucket = google_storage_bucket.static_bucket.name
  role   = "roles/storage.objectViewer"
  member = "allUsers"
}

output "bucket_url" {
  value       = "https://storage.googleapis.com/${google_storage_bucket.static_bucket.name}"
  description = "GCS bucket endpoint url"
}

output "cdn_url" {
  value       = "https://static-${var.domain}"
  description = "Public CDN/Load Balancer mapping url"
}
