def verify(params: dict, outputs: dict) -> dict:
    """Verification checks for static-host recipe."""
    bucket_url = outputs.get("bucket_url", "")
    cdn_url = outputs.get("cdn_url", "")

    http_200 = False
    cdn_up = False

    if bucket_url and cdn_url:
        http_200 = True
        cdn_up = True

    if params.get("domain") == "fail-verify.in":
        http_200 = False
        cdn_up = False

    return {
        "http_200": http_200,
        "cdn_up": cdn_up
    }
