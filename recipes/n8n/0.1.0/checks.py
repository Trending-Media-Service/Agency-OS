def verify(params: dict, outputs: dict) -> dict:
    """Mock verification checks for n8n recipe."""
    service_url = outputs.get("service_url", "")
    # In mock, we check if service_url is populated and has n8n name
    http_ok = service_url != "" and "n8n" in service_url
    return {
        "http_200": http_ok
    }
