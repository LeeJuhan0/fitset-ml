from app.core.config import settings
from app.deployment.models import ModelDeployment
from app.deployment.schemas import InternalModelItem, InternalPhaseModelItem


def model_url(platform: str, version: str) -> str:
    """s3 모델 경로 규칙"""
    ext = "mlpackage.zip" if platform == "ios" else "onnx"
    return f"s3://{settings.models_bucket}/{platform}/{version}/FitSet.{ext}"


def internal_item(row: ModelDeployment, meta_url: str | None) -> InternalModelItem:
    """분류 배포 행을 인터널 응답 항목으로"""
    return InternalModelItem(latest_version=row.version, model_url=row.model_key, meta_url=meta_url, updated_at=row.created_at)


def internal_phase_item(row: ModelDeployment) -> InternalPhaseModelItem:
    """렙카운팅 배포 행을 인터널 응답 항목으로, 종목 포함"""
    return InternalPhaseModelItem(
        class_name=row.class_name,
        latest_version=row.version,
        model_url=row.model_key,
        meta_url=row.meta_key,
        updated_at=row.created_at,
    )
