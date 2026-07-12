"""공통 픽스처.

ML 서버는 S3(boto3)와 MLflow에 의존한다. 단위/통합 테스트에서는 실제 AWS·MLflow에
붙지 않도록, 각 도메인 service 네임스페이스로 import된 의존 함수를 테스트마다 monkeypatch 한다.
(예: app.data.service 는 `from app.data.repository import get_index` 하므로 app.data.service.get_index 를 패치)
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)
