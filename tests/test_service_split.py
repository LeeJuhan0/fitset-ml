# ─────────────────────────────────────────────────────────────────────────────
# 서비스 분리 경계 — user_api에는 어드민 표면이, admin_api에는 유저 표면이 없어야 한다.
# 라우터가 지연 조립되므로 OpenAPI 스키마(문서 노출 라우트)와 실제 응답(문서 비노출
# 라우트·정적 마운트)으로 검증한다.
# ─────────────────────────────────────────────────────────────────────────────
from fastapi.testclient import TestClient

from admin_api.main import app as admin_app
from user_api.main import app as user_app

# 유저 정본은 /ml/v1(api-stage.* 호스트). 어드민은 /api/v1(admin-stage.* 호스트) —
# 경로 문자열이 일부 겹쳐도 호스트·서비스·인증이 달라 충돌하지 않는다.
USER_PATHS = {
    "/ml/v1/{platform}/data/presigned-url",
    "/ml/v1/{platform}/data/upload-confirm",
    "/ml/v1/{platform}/model/latest",
}


def test_user_app_exposes_exactly_three_user_endpoints():
    paths = set(user_app.openapi()["paths"])
    assert paths == USER_PATHS | {"/api/health"}


def test_user_app_has_no_admin_surface():
    # mlflow 프록시(문서 비노출)와 정적 마운트는 응답으로 확인 — 없으면 404
    bare = TestClient(user_app)
    assert bare.get("/mlflow").status_code == 404
    assert bare.get("/").status_code == 404


def test_admin_app_has_no_user_surface():
    paths = set(admin_app.openapi()["paths"])
    assert not paths & USER_PATHS                            # 유저(/ml/v1) 표면 없음
    assert any(p.startswith("/api/v1") for p in paths)       # 어드민 표면은 있음


def test_admin_app_keeps_dashboard_and_proxy(client):
    # 계정 미설정 상태 — 존재하는 표면이라면 404가 아니라 인증 계층 응답이 온다
    # (/mlflow는 라우트의 HTTPBasic이 헤더 부재로 401, "/"는 정적 가드가 미설정 잠금 503)
    assert client.get("/mlflow").status_code == 401
    assert client.get("/").status_code == 503
