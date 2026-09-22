import httpx
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.core.security import check_basic_auth

router = APIRouter()

_DROP_RESPONSE_HEADERS = {
    "connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade",
    "proxy-authenticate", "proxy-authorization", "content-encoding", "content-length",
}
_DROP_REQUEST_HEADERS = {"host", "authorization", "content-length"}

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """httpx 클라이언트 싱글톤, keep-alive"""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=settings.mlflow_proxy_target,
            timeout=30.0,
            limits=httpx.Limits(keepalive_expiry=1.0),
        )
    return _client


async def _relay(request: Request, upstream_path: str) -> Response:
    """MLflow 로 요청 중계, hop-by-hop 헤더 제거"""
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
    """/mlflow → /mlflow/ 리다이렉트"""
    return RedirectResponse(url="/mlflow/")


@router.api_route(
    "/graphql",
    methods=["GET", "POST"],
    dependencies=[Depends(check_basic_auth)],
    include_in_schema=False,
)
async def graphql_passthrough(request: Request) -> Response:
    """/graphql 을 MLflow 로 중계"""
    return await _relay(request, "/mlflow/graphql")


@router.api_route(
    "/mlflow/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    dependencies=[Depends(check_basic_auth)],
    include_in_schema=False,
)
async def mlflow_proxy(request: Request, path: str) -> Response:
    """/mlflow/* 전 메서드 중계"""
    return await _relay(request, f"/mlflow/{path}")
