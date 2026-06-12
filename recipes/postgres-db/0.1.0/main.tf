variable "db_name" {
  type        = string
  description = "Name of the database"
}

variable "tier" {
  type        = string
  default     = "shared"
  description = "Database tier (shared/dedicated)"
}

output "connection_uri" {
  value       = "postgresql://aos-user:mock-pass@neon-host.in/${var.db_name}"
  description = "Full connection URI for the database"
}

output "db_host" {
  value       = "neon-host.in"
  description = "Hostname of the database"
}
