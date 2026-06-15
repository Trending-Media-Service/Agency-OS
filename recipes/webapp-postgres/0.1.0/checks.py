import urllib.request
import urllib.error
import time
import logging

logger = logging.getLogger(__name__)

def _check_url_with_retry(url: str, retries: int = 6, initial_delay: float = 2.0) -> bool:
    delay = initial_delay
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    return True
        except Exception as e:
            logger.info(f"Checking {url} failed on attempt {attempt+1}/{retries}: {e}")
        
        if attempt < retries - 1:
            time.sleep(delay)
            delay *= 2
    return False

def verify(params: dict, outputs: dict) -> dict:
    """Verification checks for webapp-postgres recipe."""
    frontend_url = outputs.get("frontend_url", "")
    api_url = outputs.get("api_url", "")

    http_200 = False
    db_reachable = False

    if frontend_url:
        http_200 = _check_url_with_retry(frontend_url)

    if api_url:
        # Check /healthz or fallback to base url
        healthz_url = f"{api_url}/healthz"
        db_reachable = _check_url_with_retry(healthz_url)
        if not db_reachable:
            # Fallback to base API url
            db_reachable = _check_url_with_retry(api_url)

    return {
        "http_200": http_200,
        "db_reachable": db_reachable
    }
