variable "shop_url" {
  type = string
}

variable "secret_ref" {
  type = string
}

variable "gcp_project" {
  type = string
}

# In a real environment, this might provision resources, set up Cloud Run for the MCP server,
# or create GCP Secrets. We output mock credentials and endpoints.
output "service_url" {
  value = "https://${var.shop_url}"
}

output "mcp_server_url" {
  value = "https://mcp-shopify.${var.gcp_project}.run.app/rpc"
}
