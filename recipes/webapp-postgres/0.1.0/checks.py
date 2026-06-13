import urllib.request
import urllib.error

def verify(params: dict, outputs: dict) -> dict:
    """Verification checks for webapp-postgres recipe."""
    frontend_url = outputs.get("frontend_url", "")
    api_url = outputs.get("api_url", "")

    http_200 = False
    db_reachable = False

    if frontend_url:
        try:
            req = urllib.request.Request(frontend_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    http_200 = True
        except Exception:
            pass

    if api_url:
        try:
            healthz_url = f"{api_url}/healthz"
            req = urllib.request.Request(healthz_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    db_reachable = True
        except Exception:
            pass

    return {
        "http_200": http_200,
        "db_reachable": db_reachable
    }
