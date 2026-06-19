from prometheus_client import Counter, Gauge, Histogram, REGISTRY

if "aos_connector_operations_total" in REGISTRY._names_to_collectors:
    CONNECTOR_OPERATIONS = REGISTRY._names_to_collectors["aos_connector_operations_total"]
else:
    CONNECTOR_OPERATIONS = Counter(
        "aos_connector_operations_total",
        "Total number of connector operations (connect, verify, rotate) executed",
        ["operation", "provider", "result"]
    )

if "aos_outbox_dead_gauge" in REGISTRY._names_to_collectors:
    OUTBOX_DEAD_GAUGE = REGISTRY._names_to_collectors["aos_outbox_dead_gauge"]
else:
    OUTBOX_DEAD_GAUGE = Gauge(
        "aos_outbox_dead_gauge",
        "Total number of DEAD (poison) items in the outbox queue"
    )

if "aos_circuit_breaker_trips_total" in REGISTRY._names_to_collectors:
    CIRCUIT_BREAKER_TRIPS = REGISTRY._names_to_collectors["aos_circuit_breaker_trips_total"]
else:
    CIRCUIT_BREAKER_TRIPS = Counter(
        "aos_circuit_breaker_trips_total",
        "Total number of circuit breaker trips by domain",
        ["domain"]
    )

if "aos_approval_latency_seconds" in REGISTRY._names_to_collectors:
    APPROVAL_LATENCY = REGISTRY._names_to_collectors["aos_approval_latency_seconds"]
else:
    APPROVAL_LATENCY = Histogram(
        "aos_approval_latency_seconds",
        "Time taken for an operator to decide (approve/reject) a proposed operation in seconds",
        ["domain", "action"],
        buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 300.0, 600.0, 1800.0, 3600.0, 18000.0, 86400.0]
    )
