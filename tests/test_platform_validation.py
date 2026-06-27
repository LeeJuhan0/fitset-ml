"""플랫폼 엄격 분리 원칙(ml-02 architecture):
`{platform}` 은 ios | android 만 허용, 그 외 값은 즉시 400."""

import pytest

# (method, path 템플릿) — 모든 라우터가 validate_platform 의존성을 공유한다.
ENDPOINTS = [
    ("get", "/api/v1/{p}/data"),
    ("get", "/api/v1/{p}/data/presigned-url?filename=a.csv&class=SQUAT"),
    ("get", "/api/v1/{p}/train/status?jobId=x"),
    ("get", "/api/v1/{p}/model/latest"),
    ("get", "/api/v1/{p}/model/version-stats"),
    ("get", "/api/v1/{p}/runs"),
]


@pytest.mark.parametrize("method,path", ENDPOINTS)
@pytest.mark.parametrize("bad", ["web", "iOS", "android2", "watchos", ""])
def test_invalid_platform_returns_400(client, method, path, bad):
    url = path.format(p=bad)
    resp = getattr(client, method)(url)
    # 빈 문자열은 라우트 미스로 404가 날 수 있으므로 제외 처리
    if bad == "":
        assert resp.status_code in (400, 404)
    else:
        assert resp.status_code == 400


@pytest.mark.parametrize("good", ["ios", "android"])
def test_valid_platform_passes_validation(client, monkeypatch, good):
    # 검증 통과 후 S3 호출은 막는다 — 검증 자체만 확인
    import app.api.data as data_mod
    monkeypatch.setattr(data_mod, "get_index", lambda p: {"platform": p, "files": []})

    resp = client.get(f"/api/v1/{good}/data")
    assert resp.status_code == 200
    assert resp.json()["data"]["platform"] == good
