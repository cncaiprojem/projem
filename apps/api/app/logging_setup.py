import json
import logging
import sys
from typing import Any

from .logging.pii import mask_pii_in_json


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # noqa: D401
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        # Zorunlu alanlar (varsa bağla)
        for key in [
            "request_id",
            "job_id",
            "queue",
            "task",
            "model",
            "effort",
            "freecad_version",
            "elapsed_ms",
        ]:
            if hasattr(record, key):
                val = getattr(record, key)
                if val is not None:
                    payload[key] = val
        if hasattr(record, "request_id") and record.request_id:
            payload["request_id"] = record.request_id
        if hasattr(record, "user_id") and record.user_id:
            payload["user_id"] = record.user_id
        return json.dumps(mask_pii_in_json(payload), ensure_ascii=False)


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(name)


