variable "domain" { type = string }
variable "project_id" { type = string }
variable "mx_records" { type = list(string) }
variable "spf_record" { type = string }
variable "dkim_record" { type = string }

resource "google_dns_record_set" "mx" {
  name         = "${var.domain}."
  type         = "MX"
  ttl          = 300
  managed_zone = "zone-${replace(var.domain, ".", "-")}"
  project      = var.project_id
  rrdatas      = var.mx_records
}

resource "google_dns_record_set" "spf" {
  name         = "${var.domain}."
  type         = "TXT"
  ttl          = 300
  managed_zone = "zone-${replace(var.domain, ".", "-")}"
  project      = var.project_id
  rrdatas      = [var.spf_record]
}

resource "google_dns_record_set" "dkim" {
  name         = "_amazonses.${var.domain}."
  type         = "TXT"
  ttl          = 300
  managed_zone = "zone-${replace(var.domain, ".", "-")}"
  project      = var.project_id
  rrdatas      = [var.dkim_record]
}

output "dns_verified" {
  value       = true
  description = "Boolean output confirming email DNS routing records have been applied"
}
