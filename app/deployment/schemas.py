from enum import StrEnum

from pydantic import AwareDatetime

from app.core.schemas import CamelModel


class DeployEnv(StrEnum):
    """배포 환경, dev 실험용, prod 실사용자용"""
    DEV = "dev"
    PROD = "prod"


class DeployEnvRequest(CamelModel):
    """배포 대상 환경 바디"""
    env: DeployEnv


class DeployRequest(DeployEnvRequest):
    """분류 deploy 바디, version 과 env"""
    version: str


class DeployResponse(CamelModel):
    """deploy 응답, 환경 배포 버전 시각"""
    deployed_version: str
    platform: str
    env: DeployEnv
    deployed_at: str


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
    """인터널 최신 모델 응답, 환경별 분류와 렙카운팅"""
    env: DeployEnv
    classifier: InternalModelItem | None = None
    phase_models: list[InternalPhaseModelItem]


class InternalModelsRequest(CamelModel):
    """인터널 조회 쿼리, env 필수"""
    env: DeployEnv
