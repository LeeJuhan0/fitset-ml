# ─────────────────────────────────────────────────────────────────────────────
# 공유 응답 스키마 — 팀 API 규약(ai-server·스프링 백엔드와 동일)의 traceId + data/error 형식.
# 성공: {traceId, data} / 실패: {traceId, error: {code, message, details}}
# 실패 응답은 라우터가 만들지 않는다 — 전역 예외 핸들러(main.py)가 조립한다.
# 코드 컨벤션: 필드는 snake_case, JSON 와이어는 camelCase — alias로 양쪽 유지.
# ─────────────────────────────────────────────────────────────────────────────
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel   # snake_case → camelCase 자동 alias

T = TypeVar("T")   # data에 담기는 타입


class CamelModel(BaseModel):
    # populate_by_name=True: 코드에서는 snake_case로도, 와이어 dict의 camelCase로도 채울 수 있다.
    # FastAPI가 응답을 직렬화할 때는 alias(camelCase)로 내보낸다(response_model_by_alias 기본값).
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ApiResponse(CamelModel, Generic[T]):
    # 성공 응답: {traceId, data}. trace_id는 미들웨어가 채운 값을 deps.get_trace_id로 주입받는다.
    trace_id: str
    data: T


class ErrorDetail(CamelModel):
    # 필드 단위 검증 오류. value는 클라가 보낸 원본 값이라 어떤 JSON 타입이든 올 수 있다.
    field: str
    value: Any = None
    reason: str


class ErrorBody(CamelModel):
    # 실패 응답의 error 부분. code는 시맨틱 코드(예: NOT_FOUND, INVALID_REQUEST).
    code: str
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)


class ErrorResponse(CamelModel):
    # 실패 응답 전체 형태: {traceId, error}. OpenAPI 문서화용 — 실제 조립은 main.py 핸들러.
    trace_id: str
    error: ErrorBody
