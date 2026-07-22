# ─────────────────────────────────────────────────────────────────────────────
# 공유 응답 스키마 — 모든 도메인 응답이 쓰는 공통 봉투(Envelope). core 레이어.
# 코드 컨벤션: 필드는 snake_case, JSON 와이어는 camelCase(앱과의 규약) — alias로 양쪽 유지.
# ─────────────────────────────────────────────────────────────────────────────
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel   # snake_case → camelCase 자동 alias

T = TypeVar("T")   # 봉투에 담기는 data의 타입


class CamelModel(BaseModel):
    # populate_by_name=True: 코드에서는 snake_case로도, 와이어 dict의 camelCase로도 채울 수 있다.
    # FastAPI가 응답을 직렬화할 때는 alias(camelCase)로 내보낸다(response_model_by_alias 기본값).
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Envelope(CamelModel, Generic[T]):
    # 모든 엔드포인트의 공통 응답 형태: {success, code, message?, data}
    success: bool = True
    code: str
    message: str | None = None
    data: T
