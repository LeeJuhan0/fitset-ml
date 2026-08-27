"""플랫폼 엄격 분리 원칙(ml-02 architecture):
`{platform}` 은 ios | android 만 허용, 그 외 값은 즉시 400.
어드민 경로는 Basic 인증을 통과한 뒤에도 같은 규칙이 적용되는지 본다."""

import pytest

# (픽스처 이름, method, path 템플릿) — 모든 라우터가 validate_platform 의존성을 공유한다.
ENDPOINTS = [
    ("user_client", "get", "/ml/v1/{p}/data/presigned-url?filename=a.csv&class=SQUAT"),
    ("user_client", "get", "/ml/v1/{p}/model/latest"),
    ("admin_client", "get", "/api/v1/{p}/data"),
    ("admin_client", "get", "/api/v1/{p}/train/status?jobId=x"),
    ("admin_client", "get", "/api/v1/{p}/model/version-stats"),
    ("admin_client", "get", "/api/v1/{p}/runs"),
]


@pytest.mark.parametrize("fixture,method,path", ENDPOINTS)
@pytest.mark.parametrize("bad", ["web", "iOS", "android2", "watchos", ""])
def test_invalid_platform_returns_400(request, fixture, method, path, bad):
    http = request.getfixturevalue(fixture)   # user_client | admin_client
    url = path.format(p=bad)
    resp = getattr(http, method)(url)
    # 빈 문자열은 라우트 미스로 404가 날 수 있으므로 제외 처리
    if bad == "":
        assert resp.status_code in (400, 404)
    else:
        assert resp.status_code == 400


@pytest.mark.parametrize("good", ["ios", "android"])
def test_valid_platform_passes_validation(admin_client, monkeypatch, good):
    # 검증 통과 후 S3 호출은 막는다 — 검증 자체만 확인
    import app.data.service as data_mod
    monkeypatch.setattr(data_mod, "get_index", lambda p: {"platform": p, "files": []})

    resp = admin_client.get(f"/api/v1/{good}/data")
    assert resp.status_code == 200
    assert resp.json()["data"]["platform"] == good
