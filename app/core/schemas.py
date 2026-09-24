from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from sqlmodel import Field, SQLModel

from app.core.models import WIRE

T = TypeVar("T")


class CamelModel(SQLModel):
    """스키마 베이스, SQLModel 비테이블, camelCase alias"""
    model_config = WIRE


class ApiResponse(BaseModel, Generic[T]):
    """성공 봉투, 제네릭이라 pydantic BaseModel"""
    model_config = WIRE
    trace_id: str
    data: T


class ErrorDetail(CamelModel):
    """필드 단위 검증 오류"""
    field: str
    value: Any = None
    reason: str


class ErrorBody(CamelModel):
    """실패 봉투의 error"""
    code: str
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)


class ErrorResponse(CamelModel):
    """실패 봉투, OpenAPI 문서화용"""
    trace_id: str
    error: ErrorBody


class FilenameRequest(CamelModel):
    """?filename= 쿼리"""
    filename: str
