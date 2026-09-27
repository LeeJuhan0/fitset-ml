from pydantic import AwareDatetime

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


class InternalModelItem(CamelModel):
    """인터널 분류 모델 항목, s3 키와 배포 시각"""
    latest_version: str
    model_url: str
    meta_url: str | None = None
    updated_at: AwareDatetime


class InternalPhaseModelItem(InternalModelItem):
    """인터널 렙카운팅 모델 항목, 종목 포함"""
    class_name: str


class InternalModelsResponse(CamelModel):
    """인터널 최신 모델 응답, 분류와 종목별 렙카운팅"""
    classifier: InternalModelItem | None = None
    phase_models: list[InternalPhaseModelItem]
