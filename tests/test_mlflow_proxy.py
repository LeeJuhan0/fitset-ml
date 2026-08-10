"""MLflow UI 역프록시(/mlflow/*) 테스트.

실제 MLflow 서버 없이 검증한다 — 인증은 설정(settings)을 monkeypatch로 바꾸고,
중계는 모듈 전역 httpx 클라이언트(_client)를 스텁으로 갈아끼운다.
"""

import base64

import httpx
import pytest

from app import mlflow_proxy
from app.core.config import settings


def _basic_header(user: str, password: str) -> dict:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def creds(monkeypatch):
    # 프록시 자격증명이 설정된 상태를 흉내낸다
    monkeypatch.setattr(settings, "mlflow_ui_user", "mlops")
    monkeypatch.setattr(settings, "mlflow_ui_password", "secret")


class _StubResponse:
    # 프록시가 사용하는 최소 응답 형태 — 진짜 httpx.Response는 content-encoding 헤더를
    # 보면 본문을 재해제하려 해서(평문이면 DecodingError) 헤더 통과 검증에 못 쓴다
    status_code = 200
    content = b"<html>mlflow</html>"
    headers = httpx.Headers({"content-type": "text/html", "content-encoding": "gzip", "x-upstream": "1"})


class _StubUpstream:
    # httpx.AsyncClient.request 흉내 — 마지막 호출 인자를 기록하고 고정 응답을 돌려준다
    def __init__(self):
        self.last_kwargs = None

    async def request(self, method, url, headers=None, content=None):
        self.last_kwargs = {"method": method, "url": url, "headers": headers, "content": content}
        return _StubResponse()


@pytest.fixture
def upstream(monkeypatch):
    stub = _StubUpstream()
    monkeypatch.setattr(mlflow_proxy, "_client", stub)
    return stub


def test_인증정보_없으면_401과_로그인창_유도(client, creds):
    res = client.get("/mlflow/")
    assert res.status_code == 401
    # WWW-Authenticate가 있어야 브라우저가 로그인창을 띄운다 — 전역 예외 핸들러의 헤더 보존 검증
    assert "Basic" in res.headers.get("www-authenticate", "")


def test_잘못된_비밀번호는_401(client, creds):
    res = client.get("/mlflow/", headers=_basic_header("mlops", "wrong"))
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "UNAUTHORIZED"


def test_자격증명_미설정이면_503_잠금(client, monkeypatch):
    monkeypatch.setattr(settings, "mlflow_ui_user", "")
    monkeypatch.setattr(settings, "mlflow_ui_password", "")
    res = client.get("/mlflow/", headers=_basic_header("anyone", "anything"))
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "MLFLOW_UI_LOCKED"


def test_정상_인증이면_원서버_응답을_중계(client, creds, upstream):
    res = client.get("/mlflow/", headers=_basic_header("mlops", "secret"))
    assert res.status_code == 200
    assert res.content == b"<html>mlflow</html>"
    assert res.headers["x-upstream"] == "1"


def test_중계_응답에서_압축_헤더는_제거(client, creds, upstream):
    # httpx가 압축을 이미 풀어 돌려주므로 content-encoding이 남으면 브라우저가 이중 해제한다
    res = client.get("/mlflow/", headers=_basic_header("mlops", "secret"))
    assert "content-encoding" not in res.headers


def test_경로와_쿼리를_그대로_전달(client, creds, upstream):
    client.get("/mlflow/ajax-api/2.0/mlflow/experiments/search?max_results=10",
               headers=_basic_header("mlops", "secret"))
    url = upstream.last_kwargs["url"]
    assert url.path == "/mlflow/ajax-api/2.0/mlflow/experiments/search"
    assert url.query == b"max_results=10"


def test_요청의_인증헤더는_원서버로_흘리지_않음(client, creds, upstream):
    client.get("/mlflow/", headers=_basic_header("mlops", "secret"))
    forwarded = {k.lower() for k in upstream.last_kwargs["headers"]}
    assert "authorization" not in forwarded
    assert "host" not in forwarded


def test_슬래시_없는_진입은_리다이렉트(client, creds):
    res = client.get("/mlflow", headers=_basic_header("mlops", "secret"), follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == "/mlflow/"


def test_프리픽스_없는_graphql도_인증_후_중계(client, creds, upstream):
    # MLflow 3.x UI 일부(genai 화면)가 /graphql 을 프리픽스 없이 부른다 — 405로 떨어지면 안 됨
    res = client.post("/graphql", headers=_basic_header("mlops", "secret"), json={"query": "{ __typename }"})
    assert res.status_code == 200
    assert upstream.last_kwargs["url"].path == "/mlflow/graphql"


def test_프리픽스_없는_graphql도_인증은_필수(client, creds):
    res = client.post("/graphql", json={"query": "{ __typename }"})
    assert res.status_code == 401


def test_끊긴_커넥션은_한_번_재시도(client, creds, monkeypatch):
    # 첫 시도에서 RemoteProtocolError(유휴로 끊긴 keep-alive), 재시도는 성공하는 상황
    stub = _StubUpstream()
    calls = {"n": 0}

    async def flaky_request(method, url, headers=None, content=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        return await stub.request(method, url, headers=headers, content=content)

    monkeypatch.setattr(mlflow_proxy, "_client", type("C", (), {"request": staticmethod(flaky_request)})())
    res = client.get("/mlflow/", headers=_basic_header("mlops", "secret"))
    assert res.status_code == 200
    assert calls["n"] == 2
