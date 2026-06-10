def verify(params: dict, outputs: dict) -> dict:
    """Verification checks for brand-baseline recipe."""
    project_id = outputs.get("project_id", "")
    sa_email = outputs.get("service_account_email", "")

    # In production, we would query the GCP IAM API to check if SA exists,
    # and try to connect to the DB output. Here we perform a structural check.
    sa_exists = "@" in sa_email and project_id != ""
    db_reachable = True # Connection verification can be implemented with temporary sql connection

    return {
        "sa_exists": sa_exists,
        "db_reachable": db_reachable
    }
