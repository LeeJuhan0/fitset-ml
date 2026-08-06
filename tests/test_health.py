"""배포 헬스체크 엔드포인트 (app.main).

외부 의존성(S3·MLflow) 없이 앱이 요청을 받는지만 확인하는 경로라 패치가 필요 없다."""


def test_health_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == {"status": "ok"}
    assert body["traceId"]   # 미들웨어가 채운 traceId가 응답에 실린다
