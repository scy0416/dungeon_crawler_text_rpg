import json
import logging

from app.observability import JsonFormatter, correlation_id


def test_json_formatter_includes_correlation_id_and_extra() -> None:
    record = logging.makeLogRecord(
        {"name": "app.test", "levelname": "INFO", "msg": "hello %s", "args": ("world",),
         "event_id": "e-1"}
    )
    token = correlation_id.set("req-1")
    try:
        line = JsonFormatter("gateway").format(record)
    finally:
        correlation_id.reset(token)
    payload = json.loads(line)
    assert payload["service"] == "gateway"
    assert payload["msg"] == "hello world"
    assert payload["correlation_id"] == "req-1"
    assert payload["event_id"] == "e-1"
