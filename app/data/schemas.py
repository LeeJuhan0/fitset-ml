from sqlmodel import Field

from app.data.models import DatasetFileRead
from app.core.schemas import CamelModel


class UploadConfirmRequest(CamelModel):
    """upload-confirm 바디, filename class_name"""
    filename: str
    class_name: str


class ListDataResponse(CamelModel):
    """data 응답, 목록 목록"""
    platform: str
    files: list[DatasetFileRead]


class ChannelStats(CamelModel):
    """채널 통계, mean min max std"""
    channel: str
    mean: float
    min: float
    max: float
    std: float


class FileStatsResponse(CamelModel):
    """stats 응답, 트림 정보와 채널 통계"""
    filename: str
    class_name: str = Field(alias="class")
    trim_seconds: float
    trim_applied: bool
    duration_seconds: float
    total_rows: int
    used_rows: int
    channels: list[ChannelStats]


class PresignedUrlResponse(CamelModel):
    """presigned-url 응답, PUT URL 파일명"""
    presigned_url: str
    expires_in: int
    s3_key: str
    filename: str


class UploadConfirmResponse(CamelModel):
    """upload-confirm 응답, filename class"""
    filename: str
    class_name: str = Field(alias="class")


class PresignedUrlRequest(CamelModel):
    """?class=&deviceId= 쿼리, 채번 주인과 종목"""
    class_name: str
    device_id: str
