from contextvars import ContextVar
import datetime as dt
import json
import logging
from typing import Any, Optional

# Context variable to hold the trace ID for the current async task
trace_context: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)


class StructuredJsonFormatter(logging.Formatter):
    """Custom logging formatter that outputs logs in JSON format,
    injecting trace ID and tenant ID automatically."""
    
    def format(self, record: logging.LogRecord) -> str:
        # Import dynamically to prevent circular imports if middleware isn't loaded yet
        from app.middleware import tenant_context
        
        log_data: dict[str, Any] = {
            "timestamp": dt.datetime.fromtimestamp(record.created, dt.timezone.utc).isoformat(),
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
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
            log_data["exception"] = self.formatException(record.exc_info)
            
        # Incorporate extra fields passed to logger.info("msg", extra={...})
        for k, v in record.__dict__.items():
            if k not in {"args", "asctime", "created", "exc_info", "exc_text", "filename",
                         "funcName", "levelname", "levelno", "lineno", "module", "msecs",
                         "message", "msg", "name", "pathname", "process", "processName",
                         "relativeCreated", "stack_info", "thread", "threadName"}:
                log_data[k] = v
                
        return json.dumps(log_data, default=str)


def setup_logging(level: str = "INFO", json_format: bool = False) -> None:
    """Configures the root logger to use JSON formatting or standard text formatting."""
    root = logging.getLogger()
    root.setLevel(level)
    
    # Remove existing handlers
    for h in root.handlers[:]:
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
        class StandardTextFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                record.trace_id = trace_context.get() or "none"
                return super().format(record)
                
        handler.setFormatter(StandardTextFormatter(formatter._fmt))
        
    root.addHandler(handler)
