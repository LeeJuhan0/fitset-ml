from typing import Any

from pydantic import model_validator

from sqlmodel import Field

from app.labeling.models import CollectFileRead
from app.core.schemas import CamelModel


class PresignedPairResponse(CamelModel):
    """presigned-url 응답, CSV 영상 PUT URL 2개"""
    filename: str
    csv_url: str
    csv_key: str
    video_url: str
    video_key: str
    expires_in: int


class UploadConfirmRequest(CamelModel):
    """upload-confirm 바디, filename, videoStart, rows"""
    filename: str
    video_start: float
    rows: int | None = None


class UploadConfirmResponse(CamelModel):
    """upload-confirm 응답, filename, status"""
    filename: str
    status: str


class ChangeClassRequest(CamelModel):
    """종목 변경 바디, filename, class"""
    filename: str
    class_name: str = Field(alias="class")


class DeleteFileResponse(CamelModel):
    """파일 삭제 응답, 삭제된 filename"""
    filename: str


class ListFilesResponse(CamelModel):
    """files 응답, 목록 전체, 상태별 개수"""
    platform: str
    files: list[CollectFileRead]
    counts: dict[str, int]


class LabelRequest(CamelModel):
    """label 바디, filenames"""
    filenames: list[str]

    @model_validator(mode="before")
    @classmethod
    def dedup_filenames(cls, data: dict):
        """중복·빈 이름 제거, 순서 유지"""
        names = data.get("filenames")
        if isinstance(names, list):
            data["filenames"] = list(dict.fromkeys(n for n in names if n))
        return data


class SkippedFile(CamelModel):
    """라벨링 건너뛴 파일, 사유"""
    filename: str
    reason: str


class LabelResponse(CamelModel):
    """label 응답, accepted, skipped"""
    accepted: list[str]
    skipped: list[SkippedFile]


class VideoUrlResponse(CamelModel):
    """video-url 응답, presigned GET, 만료 초"""
    filename: str
    url: str
    expires_in: int


class PoseResponse(CamelModel):
    """pose 응답, fps, 프레임별 phase, 관절 33개"""
    filename: str
    fps: float
    frames: list[Any]


class PromoteRequest(CamelModel):
    """promote 바디, filenames"""
    filenames: list[str]

    @model_validator(mode="before")
    @classmethod
    def dedup_filenames(cls, data: dict):
        """중복·빈 이름 제거, 순서 유지"""
        names = data.get("filenames")
        if isinstance(names, list):
            data["filenames"] = list(dict.fromkeys(n for n in names if n))
        return data


class PromoteResponse(CamelModel):
    """promote 응답, promoted, skipped"""
    promoted: list[str]
    skipped: list[SkippedFile]
