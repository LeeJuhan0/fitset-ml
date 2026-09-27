from collections import Counter

from app.core.config import settings
from app.deployment.models import ModelDeployment
from app.deployment.schemas import InternalModelItem, InternalPhaseModelItem

REPORT_WINDOW_SECONDS = 24 * 3600


def model_url(platform: str, version: str) -> str:
    """s3 모델 경로 규칙"""
    ext = "mlpackage.zip" if platform == "ios" else "onnx"
    return f"s3://{settings.models_bucket}/{platform}/{version}/FitSet.{ext}"


def is_active(report_ts: float, now: float) -> bool:
    """리포트가 24시간 윈도우 안인지"""
    return now - report_ts < REPORT_WINDOW_SECONDS


def aggregate_reports(reports, now: float) -> Counter:
    """윈도우 안의 리포트를 버전별로 센다 (순수 계산)"""
    return Counter(v for ts, v in reports if is_active(ts, now))


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
