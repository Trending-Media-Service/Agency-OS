variable "domain" { type = string }
variable "project_id" { type = string }
variable "bucket_name" { type = string }
variable "region" {
  type    = string
  default = "asia-south2"
}

# 1. GCS Bucket for website hosting
resource "google_storage_bucket" "static_bucket" {
  name          = var.bucket_name
  location      = var.region
  project       = var.project_id
  force_destroy = true

  uniform_bucket_level_access = true

  website {
    main_page_suffix = "index.html"
    not_found_page   = "404.html"
  }
}

# 2. Make bucket contents public read-only
resource "google_storage_bucket_iam_member" "public_read" {
  bucket = google_storage_bucket.static_bucket.name
  role   = "roles/storage.objectViewer"
  member = "allUsers"
}

# 3. Compute Backend Bucket with Cloud CDN enabled
resource "google_compute_backend_bucket" "cdn_backend" {
  name        = "${var.bucket_name}-backend"
  bucket_name = google_storage_bucket.static_bucket.name
  enable_cdn  = true
  project     = var.project_id
}

# 4. Managed SSL Certificate for custom domain
resource "google_compute_managed_ssl_certificate" "ssl_cert" {
  name    = "${replace(var.domain, ".", "-")}-cert"
  project = var.project_id
  managed {
    domains = [var.domain]
  }
}

# 5. URL Map
resource "google_compute_url_map" "url_map" {
  name            = "${var.bucket_name}-url-map"
  project         = var.project_id
  default_service = google_compute_backend_bucket.cdn_backend.id
}

# 6. Target HTTPS Proxy
resource "google_compute_target_https_proxy" "https_proxy" {
  name             = "${var.bucket_name}-https-proxy"
  project          = var.project_id
  url_map          = google_compute_url_map.url_map.id
  ssl_certificates = [google_compute_managed_ssl_certificate.ssl_cert.id]
}

# 7. Global Forwarding Rule (Anycast IP)
resource "google_compute_global_forwarding_rule" "forwarding_rule" {
  name       = "${var.bucket_name}-forwarding-rule"
  project    = var.project_id
  target     = google_compute_target_https_proxy.https_proxy.id
  port_range = "443"
  ip_address = google_compute_global_address.lb_ip.address
}

# 8. Reserved Global IP Address
resource "google_compute_global_address" "lb_ip" {
  name    = "${var.bucket_name}-ip"
  project = var.project_id
}

output "bucket_url" {
  value       = "https://storage.googleapis.com/${google_storage_bucket.static_bucket.name}"
  description = "GCS bucket endpoint url"
}

output "cdn_url" {
  value       = "https://${var.domain}"
  description = "Public CDN/Load Balancer mapping url"
}

output "lb_ip_address" {
  value       = google_compute_global_address.lb_ip.address
  description = "IP address of the Load Balancer to point DNS A records to"
}
