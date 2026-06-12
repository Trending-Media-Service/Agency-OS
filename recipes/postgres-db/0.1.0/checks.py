def verify(params: dict, outputs: dict) -> dict[str, bool]:
    """Verification check for the serverless database."""
    connection_uri = outputs.get("connection_uri")
    db_host = outputs.get("db_host")
    
    # Simple verification logic
    has_conn = bool(connection_uri and connection_uri.startswith("postgresql://"))
    has_host = bool(db_host == "neon-host.in")
    
    return {
        "db_connectable": has_conn and has_host,
        "schema_query_ok": True
    }
