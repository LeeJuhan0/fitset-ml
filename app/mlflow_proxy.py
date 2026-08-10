# ─────────────────────────────────────────────────────────────────────────────
# MLflow UI 역프록시 — /mlflow/* 를 Basic 인증 뒤에서 MLflow 서버(5001)로 단건 중계.
# MLflow가 --static-prefix /mlflow 로 떠 있어 UI 정적 자산·REST API가 전부 이 경로로
# 들어오므로, 경로를 벗기지 않고 그대로 전달하면 UI가 프록시 너머에서 완전히 동작한다.
# 응답은 통째로 받아 되돌리는 단건 방식 — UI·API 응답은 수 MB 이하라 스트리밍 불필요,
# 대용량 아티팩트는 이 경로가 아니라 S3/SSM으로 받는다.
# ─────────────────────────────────────────────────────────────────────────────
import secrets

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.core.config import settings

router = APIRouter()
basic_scheme = HTTPBasic()   # Authorization: Basic 헤더 파싱, 없으면 401 + 브라우저 로그인창

# 중계에서 제거할 헤더 — hop-by-hop 헤더와, httpx가 압축을 이미 풀어 실제 본문과
# 어긋나게 되는 content-encoding/length (그대로 두면 브라우저가 이중 해제·길이 불일치)
_DROP_RESPONSE_HEADERS = {
    "connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade",
    "proxy-authenticate", "proxy-authorization", "content-encoding", "content-length",
}
# 원 서버로 넘기지 않을 요청 헤더 — host는 httpx가 대상 기준으로 다시 쓰고(allowed-hosts
# 통과), authorization은 프록시 인증용이라 MLflow까지 흘릴 이유가 없다
_DROP_REQUEST_HEADERS = {"host", "authorization", "content-length"}

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    # 프록시 공용 커넥션 풀을 첫 요청 때 만든다(테스트에서 모듈 변수로 대체 가능)
    # keepalive_expiry는 MLflow(gunicorn)의 유휴 커넥션 종료(기본 2초)보다 짧아야 한다 —
    # 길면 상대가 이미 끊은 커넥션을 재사용하다 RemoteProtocolError 500이 난다(운영 실측)
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=settings.mlflow_proxy_target,
            timeout=30.0,
            limits=httpx.Limits(keepalive_expiry=1.0),
        )
    return _client


def check_basic_auth(credentials: HTTPBasicCredentials = Depends(basic_scheme)) -> None:
    # 자격 미설정이면 잠금(fail closed), 불일치면 401로 재입력 유도
    if not settings.mlflow_ui_user or not settings.mlflow_ui_password:
        raise HTTPException(
            status_code=503,
            detail={"code": "MLFLOW_UI_LOCKED", "message": "MLflow UI 자격증명이 설정되지 않았습니다."},
        )
    user_ok = secrets.compare_digest(credentials.username.encode(), settings.mlflow_ui_user.encode())
    password_ok = secrets.compare_digest(credentials.password.encode(), settings.mlflow_ui_password.encode())
    if user_ok and password_ok:
        return
    raise HTTPException(
        status_code=401,
        detail={"code": "UNAUTHORIZED", "message": "MLflow UI 인증에 실패했습니다."},
        headers={"WWW-Authenticate": 'Basic realm="MLflow"'},
    )


async def _relay(request: Request, upstream_path: str) -> Response:
    # 요청을 원 서버에 보내고 응답 전체를 받아 되돌린다. 본문을 미리 버퍼링해 두므로
    # 유휴로 끊긴 커넥션에 걸렸을 때(RemoteProtocolError) 새 커넥션으로 1회 재시도가 안전하다
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _DROP_REQUEST_HEADERS}
    body = await request.body()
    url = httpx.URL(path=upstream_path, query=request.url.query.encode())
    try:
        upstream = await _get_client().request(request.method, url, headers=headers, content=body)
    except httpx.RemoteProtocolError:
        upstream = await _get_client().request(request.method, url, headers=headers, content=body)
    response_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _DROP_RESPONSE_HEADERS}
    return Response(content=upstream.content, status_code=upstream.status_code, headers=response_headers)


@router.get("/mlflow", dependencies=[Depends(check_basic_auth)], include_in_schema=False)
def mlflow_root_redirect() -> RedirectResponse:
    # 슬래시 없는 진입을 UI 루트로 보정
    return RedirectResponse(url="/mlflow/")


@router.api_route(
    "/graphql",
    methods=["GET", "POST"],
    dependencies=[Depends(check_basic_auth)],
    include_in_schema=False,
)
async def graphql_passthrough(request: Request) -> Response:
    # MLflow 3.x UI 일부(genai 화면)가 static-prefix를 무시하고 /graphql 을 부른다 —
    # 프리픽스를 붙여 원 서버의 /mlflow/graphql 로 넘긴다
    return await _relay(request, "/mlflow/graphql")


@router.api_route(
    "/mlflow/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    dependencies=[Depends(check_basic_auth)],
    include_in_schema=False,
)
async def mlflow_proxy(request: Request, path: str) -> Response:
    return await _relay(request, f"/mlflow/{path}")
