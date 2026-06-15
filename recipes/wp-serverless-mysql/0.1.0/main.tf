variable "project_id" {
  type = string
}

variable "custom_domain" {
  type = string
}

variable "region" {
  type    = string
  default = "asia-south1"
}

variable "db_tier" {
  type    = string
  default = "db-f1-micro"
}

output "service_url" {
  value = "https://wordpress-app.run.app"
}

output "db_instance_name" {
  value = "wp-mysql-instance"
}

output "uploads_bucket" {
  value = "gs://wp-uploads-bucket"
}
