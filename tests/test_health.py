def test_health_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == {"status": "ok"}
    assert body["traceId"]
