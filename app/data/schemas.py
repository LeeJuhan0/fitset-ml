# ─────────────────────────────────────────────────────────────────────────────
# data 도메인 요청/응답 스키마 (Pydantic DTO). ORM이 없으므로 이것이 유일한 모델 정의다.
# ─────────────────────────────────────────────────────────────────────────────
from pydantic import BaseModel, Field

from app.core.schemas import CamelModel


class UploadConfirmRequest(BaseModel):   # POST /data/upload-confirm 바디: {filename, class_name}
    filename: str
    class_name: str   # JSON 키도 그대로 'class_name' (class는 파이썬 예약어라 snake_case 유지)


class FileEntry(CamelModel):
    # index.json의 파일 항목 하나 (GET /data 응답의 files 원소)
    filename: str
    class_name: str = Field(alias="class")   # 인덱스 JSON 키는 'class' (예약어라 alias)
    device_id: str
    collected_at: str
    uploaded: bool
    trained_in_version: str | None = None    # 아직 학습에 안 쓰였으면 None


class ListDataData(CamelModel):
    # GET /data 응답 data — index.json 본문 그대로
    platform: str
    files: list[FileEntry]


class ChannelStats(CamelModel):
    # 센서 채널 하나(ax~gz)의 요약 통계
    channel: str
    mean: float
    min: float
    max: float
    std: float


class FileStatsData(CamelModel):
    # GET /data/stats 응답 data — 앞뒤 trim_seconds 초를 제외한 채널별 통계
    filename: str
    class_name: str = Field(alias="class")
    trim_seconds: float           # 앞뒤로 잘라낸 구간(초)
    trim_applied: bool            # 파일이 너무 짧아 트림을 못 했으면 False(전체 구간 통계)
    duration_seconds: float
    total_rows: int
    used_rows: int                # 통계에 실제 사용된 샘플 수
    channels: list[ChannelStats]


class PresignedUrlData(CamelModel):
    # GET /data/presigned-url 응답 data
    presigned_url: str          # 앱이 이 URL로 CSV를 직접 PUT
    expires_in: int             # URL 유효시간(초)
    s3_key: str                 # 업로드 경로
    filename: str               # 서버가 부여한 파일명(앱이 upload-confirm에 다시 보냄)


class UploadConfirmData(CamelModel):
    # POST /data/upload-confirm 응답 data
    filename: str
    class_name: str = Field(alias="class")
