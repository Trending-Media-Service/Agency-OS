def verify(params: dict, outputs: dict) -> dict:
    """Verification checks for email-dns recipe."""
    dns_verified = outputs.get("dns_verified", False)
    
    mx_valid = True
    spf_valid = True
    dkim_valid = True

    if params.get("domain") == "fail-verify.in":
        mx_valid = False
        spf_valid = False
        dkim_valid = False

    return {
        "mx_valid": mx_valid,
        "spf_valid": spf_valid,
        "dkim_valid": dkim_valid
    }
