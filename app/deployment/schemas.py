from app.core.schemas import CamelModel


class DeployRequest(CamelModel):
    """deploy 바디, version"""
    version: str


class DeployResponse(CamelModel):
    """deploy 응답, 배포 버전 시각"""
    deployed_version: str
    platform: str
    deployed_at: str


class ModelLatestResponse(CamelModel):
    """latest 응답, 버전 URL 최신 여부"""
    latest_version: str
    model_url: str
    meta_url: str
    is_up_to_date: bool


class VersionStatItem(CamelModel):
    """버전 분포 항목, count ratio"""
    version: str
    count: int
    ratio: float


class VersionStatsResponse(CamelModel):
    """version-stats 응답, 분포 목록"""
    latest_version: str | None = None
    total_reports: int
    stats: list[VersionStatItem]
