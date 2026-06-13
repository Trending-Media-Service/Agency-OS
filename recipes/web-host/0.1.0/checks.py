import os
import urllib.request
import urllib.error

def verify(params: dict, outputs: dict) -> dict:
    """Verification checks for web-host recipe."""
    service_url = outputs.get("service_url", "")
    if not service_url:
        return {
            "http_200": False,
            "error": "No service_url output found"
        }
        
    # Bypass real network requests during unit tests
    if os.getenv("AOS_ENV") == "test":
        print(f"[TEST BYPASS] Mock verifying HTTP 200 for URL: {service_url}")
        return {
            "http_200": True
        }

    print(f"Verifying HTTP 200 on service URL: {service_url}")
    try:
        req = urllib.request.Request(service_url, headers={'User-Agent': 'AOS-Verifier'})
        with urllib.request.urlopen(req, timeout=10) as response:
            status = response.status
            print(f"Response status: {status}")
            http_ok = (status == 200)
    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code}")
        http_ok = (e.code == 200)
    except Exception as e:
        print(f"Connection Error: {e}")
        http_ok = False

    return {
        "http_200": http_ok
    }
