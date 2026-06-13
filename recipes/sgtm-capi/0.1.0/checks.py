def verify(params: dict, outputs: dict) -> dict:
    """Verification checks for sgtm-capi recipe."""
    sgtm_url = outputs.get("sgtm_url", "")
    dns_verified = outputs.get("dns_verified", False)

    sgtm_healthy = False
    secrets_configured = False

    if sgtm_url and dns_verified:
        sgtm_healthy = True
        
    if params.get("capi_pixel_id") and params.get("capi_access_token"):
        secrets_configured = True

    return {
        "sgtm_healthy": sgtm_healthy,
        "secrets_configured": secrets_configured
    }
