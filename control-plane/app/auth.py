import os
import logging
import hmac
from fastapi import Header, HTTPException, Request

logger = logging.getLogger(__name__)

OPERATOR_TOKEN = os.getenv("OPERATOR_TOKEN", "default-dev-token")
WORKER_SA = os.getenv("AOS_WORKER_SERVICE_ACCOUNT")
AOS_ENV = os.getenv("AOS_ENV", "development")

if os.getenv("ENV") == "production" and OPERATOR_TOKEN == "default-dev-token":
    raise RuntimeError("PRODUCTION BOOT ERROR: OPERATOR_TOKEN must be explicitly set — default is forbidden")


async def verify_operator_auth(authorization: str | None = Header(default=None)):
    """Verifies that the request carries a valid Operator Bearer Token in the Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header")
    token = authorization[7:]
    if not hmac.compare_digest(token, OPERATOR_TOKEN):
        raise HTTPException(403, "Forbidden: Invalid operator token")


async def resolved_operator_role(authorization: str | None = Header(default=None)) -> str | None:
    """Resolves the operator's role if authenticated, else returns None."""
    if not authorization:
        return None
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header")
    token = authorization[7:]
    if not hmac.compare_digest(token, OPERATOR_TOKEN):
        raise HTTPException(403, "Forbidden: Invalid operator token")
    return "OPERATOR_AUTHENTICATED"


async def verify_worker_auth(request: Request, authorization: str | None = Header(default=None)):
    if AOS_ENV == "test" or not WORKER_SA:
        return

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header")

    token = authorization[7:]
    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests
        google_request = google_requests.Request()
        aud_base = f"{request.url.scheme}://{request.url.netloc}{request.url.path}"
        info = id_token.verify_oauth2_token(token, google_request, audience=aud_base)

        if info.get("iss") not in ["accounts.google.com", "https://accounts.google.com"]:
            raise ValueError("Wrong issuer")

        email = info.get("email")
        if email != WORKER_SA:
            raise ValueError(f"Unauthorized service account: {email}")

    except Exception as e:
        logger.error(f"OIDC token verification failed: {e}")
        raise HTTPException(401, f"Unauthorized: {e}")
