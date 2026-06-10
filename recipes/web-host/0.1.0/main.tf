variable "domain" {
  type = string
}

variable "region" {
  type    = string
  default = "asia-south1"
}

output "service_url" {
  value = "https://web-${var.domain}"
}

output "dns_zone" {
  value = "zone-${var.domain}"
}

output "cert_id" {
  value = "cert-123"
}
