# ─────────────────────────────────────────────────────────────────────────────
# deployment 도메인 요청/응답 스키마 (Pydantic DTO).
# ─────────────────────────────────────────────────────────────────────────────
from pydantic import BaseModel

from app.core.schemas import CamelModel


class DeployRequest(BaseModel):   # POST /deploy 바디
    version: str                  # 배포할 버전(예: v1.3)


class DeployData(CamelModel):
    # POST /deploy 응답 data
    deployed_version: str
    platform: str
    deployed_at: str              # 배포 시각(UTC ISO)


class ModelLatestData(CamelModel):
    # GET /model/latest 응답 data
    latest_version: str
    model_url: str                # 임시 서명 HTTPS 다운로드 URL
    is_up_to_date: bool           # 앱이 최신인지 여부


class VersionStatItem(CamelModel):
    # 버전 분포의 한 항목
    version: str
    count: int                    # 윈도우 내 리포트 수
    ratio: float                  # 전체 대비 비율


class VersionStatsData(CamelModel):
    # GET /model/version-stats 응답 data
    latest_version: str | None = None   # 미배포면 None
    total_reports: int
    stats: list[VersionStatItem]
