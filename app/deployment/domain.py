# ─────────────────────────────────────────────────────────────────────────────
# deployment 도메인 규칙 — I/O 없는 순수 함수/상수만 둔다.
# 플랫폼별 모델 포맷 규칙, 버전 리포트 집계 윈도우 규칙이 이 도메인의 불변식이다.
# ─────────────────────────────────────────────────────────────────────────────
from collections import Counter

from app.core.config import settings   # 설정 상수 — I/O 아님

# 이 기간 안의 리포트만 "현재 사용 중"으로 집계 (지나면 만료 — 빼기 연산이 필요 없음)
REPORT_WINDOW_SECONDS = 24 * 3600   # 24시간


def model_url(platform: str, version: str) -> str:
    # 모델 포맷 규칙: iOS는 mlpackage(zip), Android는 tflite — 저장 경로의 정본 조립.
    ext = "mlpackage.zip" if platform == "ios" else "tflite"
    return f"s3://{settings.models_bucket}/{platform}/{version}/FitSet.{ext}"


def is_active(report_ts: float, now: float) -> bool:
    # 윈도우 규칙: now 기준 24시간 이내 리포트만 유효
    return now - report_ts < REPORT_WINDOW_SECONDS


def aggregate_reports(reports, now: float) -> Counter:
    """윈도우 안의 리포트를 버전별로 센다 (순수 계산).

    reports: (리포트 시각, version) 튜플의 반복자.
    """
    return Counter(v for ts, v in reports if is_active(ts, now))
