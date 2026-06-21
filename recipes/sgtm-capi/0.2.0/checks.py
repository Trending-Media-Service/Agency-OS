import socket
import urllib.request

def verify(params: dict, outputs: dict) -> dict:
    """Rigorous verification checks for first-party sGTM gateway."""
    domain = params.get("domain", "")
    static_ip = outputs.get("static_ip_address", "")
    
    dns_resolves = False
    gateway_responding = False

    if domain and static_ip:
        try:
            resolved_ip = socket.gethostbyname(domain)
            if resolved_ip == static_ip:
                dns_resolves = True
        except socket.gaierror:
            pass

    if dns_resolves:
        try:
            # GTM Cloud Run container default health endpoint
            response = urllib.request.urlopen(f"https://{domain}/healthy", timeout=5)
            if response.status == 200:
                gateway_responding = True
        except Exception:
            pass

    return {
        "dns_resolves": dns_resolves,
        "gateway_responding": gateway_responding,
        "secrets_configured": bool(params.get("capi_pixel_id") and params.get("capi_access_token"))
    }
