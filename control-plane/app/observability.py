from contextvars import ContextVar
import datetime as dt
import json
import logging
import os
import re
from typing import Any, Optional

# Context variable to hold the trace ID for the current async task
trace_context: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)

PHONE_REGEX = re.compile(r'\+?(?:91|0)?[6789]\d{9}\b|\+?[1-9]\d{10,14}\b')

SENSITIVE_KEYS = {"to", "phone", "secret", "token", "password", "authorization", "key", "credential", "wamid"}

def redact_sensitive_value(key: str, value: Any) -> Any:
    """Recursively redacts sensitive values based on key names and value patterns."""
    if isinstance(value, str):
        if any(sk in key.lower() for sk in SENSITIVE_KEYS):
            return "[REDACTED]"
        # Redact raw phone numbers found within any string value
        return PHONE_REGEX.sub("[REDACTED]", value)
    elif isinstance(value, dict):
        return {k: redact_sensitive_value(k, v) for k, v in value.items()}
    elif isinstance(value, list):
        return [redact_sensitive_value(key, x) for x in value]
    return value

def redact_text(text: str) -> str:
    """Redacts phone-number-like sequences from raw text messages."""
    return PHONE_REGEX.sub("[REDACTED]", text)


class StructuredJsonFormatter(logging.Formatter):
    """Custom logging formatter that outputs logs in JSON format,
    injecting trace ID and tenant ID automatically, and redacting sensitive data."""
    
    def format(self, record: logging.LogRecord) -> str:
        # Import dynamically to prevent circular imports if middleware isn't loaded yet
        from app.middleware import tenant_context
        
        redacted_message = redact_text(record.getMessage())
        
        log_data: dict[str, Any] = {
            "timestamp": dt.datetime.fromtimestamp(record.created, dt.timezone.utc).isoformat(),
            "severity": record.levelname,
            "logger": record.name,
            "message": redacted_message,
        }
        
        # Inject trace ID if set
        trace_id = trace_context.get()
        if trace_id:
            log_data["trace_id"] = trace_id
            
        # Inject tenant ID if set
        tenant_id = tenant_context.get()
        if tenant_id:
            log_data["tenant_id"] = tenant_id
            
        # Inject exception info if present
        if record.exc_info:
            log_data["exception"] = redact_text(self.formatException(record.exc_info))
            
        # Incorporate extra fields passed to logger.info("msg", extra={...})
        for k, v in record.__dict__.items():
            if k not in {"args", "asctime", "created", "exc_info", "exc_text", "filename",
                         "funcName", "levelname", "levelno", "lineno", "module", "msecs",
                         "message", "msg", "name", "pathname", "process", "processName",
                         "relativeCreated", "stack_info", "thread", "threadName", "trace_id"}:
                log_data[k] = redact_sensitive_value(k, v)
                
        return json.dumps(log_data, default=str)


def setup_logging(level: str = "INFO", json_format: bool = False) -> None:
    """Configures the root logger to use JSON formatting or standard text formatting."""
    root = logging.getLogger()
    root.setLevel(level)
    
    # Remove existing handlers, keeping pytest handlers intact
    for h in root.handlers[:]:
        if "pytest" in type(h).__module__:
            continue
        root.removeHandler(h)
        
    handler = logging.StreamHandler()
    if json_format:
        handler.setFormatter(StructuredJsonFormatter())
    else:
        # Standard clean text log format for local development
        formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)s [%(name)s] [Trace:%(trace_id)s] %(message)s"
        )
        
        # We write a custom formatter wrapping the standard text one to dynamically inject trace_id
        # and redact sensitive data
        class StandardTextFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                record.trace_id = trace_context.get() or "none"
                formatted = super().format(record)
                return redact_text(formatted)
                
        handler.setFormatter(StandardTextFormatter(formatter._fmt))
        
    root.addHandler(handler)
