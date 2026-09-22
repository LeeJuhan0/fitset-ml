import logging

from conftest import async_

from app.core.logging import _TraceIdFilter, trace_id_var


def _record(msg: str = "hello") -> logging.LogRecord:
    return logging.LogRecord("fitset-ml", logging.INFO, __file__, 1, msg, None, None)


def test_filter_attaches_trace_id_from_contextvar():
    token = trace_id_var.set("abc123")
    try:
        record = _record()
        assert _TraceIdFilter().filter(record) is True
        assert record.trace_id == "abc123"
    finally:
        trace_id_var.reset(token)


def test_filter_defaults_to_dash_outside_request():
    record = _record()
    _TraceIdFilter().filter(record)
    assert record.trace_id == "-"


def test_filter_respects_preset_trace_id():
    record = _record()
    record.trace_id = "preset"
    _TraceIdFilter().filter(record)
    assert record.trace_id == "preset"


def test_access_log_emitted_with_method_status(admin_client, caplog, monkeypatch):
    import app.data.service as data_mod
    monkeypatch.setattr(data_mod, "list_files", async_(lambda s, p: []))

    with caplog.at_level(logging.INFO, logger="fitset-ml"):
        admin_client.get("/api/v1/ios/data")

    access = [r for r in caplog.records
              if r.name == "fitset-ml" and "/api/v1/ios/data" in r.getMessage()]
    assert len(access) == 1
    assert "GET" in access[0].getMessage() and " 200 " in access[0].getMessage()


def test_access_log_skips_health(client, caplog):
    with caplog.at_level(logging.INFO, logger="fitset-ml"):
        client.get("/api/health")
    assert not [r for r in caplog.records
                if r.name == "fitset-ml" and "/api/health" in r.getMessage()]


def test_access_log_level_follows_status(client, caplog):
    with caplog.at_level(logging.INFO, logger="fitset-ml"):
        client.get("/api/v1/ios/data")
    access = [r for r in caplog.records
              if r.name == "fitset-ml" and "/api/v1/ios/data" in r.getMessage()]
    assert len(access) == 1
    assert access[0].levelno == logging.WARNING


def test_contextvar_reset_after_request(client):
    client.get("/api/health")
    assert trace_id_var.get() == "-"
