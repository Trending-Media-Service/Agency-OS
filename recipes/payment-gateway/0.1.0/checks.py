def verify(params: dict, outputs: dict) -> dict:
    """Verification checks for payment-gateway recipe."""
    webhook_id = outputs.get("webhook_id", "")
    webhook_secret_ref = outputs.get("webhook_secret_ref", "")
    
    webhook_configured = False
    secrets_configured = False
    
    if webhook_id:
        webhook_configured = True
    if webhook_secret_ref:
        secrets_configured = True
        
    return {
        "webhook_configured": webhook_configured,
        "secrets_configured": secrets_configured
    }
