"""공통 픽스처.

ML 서버는 S3(boto3)와 MLflow에 의존한다. 단위/통합 테스트에서는 실제 AWS·MLflow에
붙지 않도록, 각 도메인 service 네임스페이스로 import된 의존 함수를 테스트마다 monkeypatch 한다.
(예: app.data.service 는 `from app.data.repository import get_index` 하므로 app.data.service.get_index 를 패치)
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from admin_api.main import app as admin_app   # 어드민 라우터·대시보드·mlflow 프록시

# 어드민 Basic 공용 계정(테스트용) — check_basic_auth가 settings와 대조한다
ADMIN_AUTH = ("admin", "admin-test-pw")


@pytest.fixture
def client():
    # 무인증 클라이언트 — 어드민 서비스 대상(정적·헬스·인증 실패 케이스 검증용)
    return TestClient(admin_app)


@pytest.fixture
def admin_client(monkeypatch):
    # 어드민 계정을 설정에 주입하고, 모든 요청에 Basic 인증이 실리는 클라이언트를 돌려준다
    monkeypatch.setattr(settings, "mlflow_ui_user", ADMIN_AUTH[0])
    monkeypatch.setattr(settings, "mlflow_ui_password", ADMIN_AUTH[1])
    c = TestClient(admin_app)
    c.auth = ADMIN_AUTH
    return c

