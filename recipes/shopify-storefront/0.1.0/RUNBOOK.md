# Shopify Storefront Deployment Runbook

## Overview
This recipe deploys the dedicated Shopify Storefront configuration for the brand. It registers connection secrets in Google Cloud Secret Manager and hooks up the Model Context Protocol (MCP) server endpoint for automated storefront management.

## Operations
1.  **Deployment**: Run via `ProvisionAdapter` with action `provision.shopify_storefront.create`.
2.  **Verification**: The verification script `checks.py` executes a tool call (`shopify_get_shop_info`) against the storefront MCP server to verify responsive API scopes.
3.  **Webhook Ingestion**: All incoming Shopify webhooks (e.g. `orders/create`) are validated using HMAC-SHA256 signatures, using credentials dynamically resolved from the brand's GCP Secret Manager project, and processed via the privilege outbox/op loop.
