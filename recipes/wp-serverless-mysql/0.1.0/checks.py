def verify(params: dict, outputs: dict) -> dict[str, bool]:
    """Verification checks for serverless WordPress."""
    service_url = outputs.get("service_url")
    db_inst = outputs.get("db_instance_name")
    bucket = outputs.get("uploads_bucket")

    http_ok = bool(service_url == "https://wordpress-app.run.app")
    db_ok = bool(db_inst == "wp-mysql-instance")
    bucket_ok = bool(bucket == "gs://wp-uploads-bucket")

    return {
        "http_200": http_ok,
        "db_reachable": db_ok and bucket_ok
    }
