# ─────────────────────────────────────────────────────────────────────────────
# deployment 도메인 Service — 배포·최신 모델 조회·버전 분포 유스케이스 조율.
# 버전 리포팅은 (시각, version)으로 쌓아 도메인 윈도우 규칙(24h)으로 집계한다.
# HTTPException을 직접 던지는 것은 계층 순수성보다 단순함을 택한 MVP 트레이드오프.
# ─────────────────────────────────────────────────────────────────────────────
import time                                    # 리포트 시각 기록
from collections import defaultdict, deque    # 자동 초기화 dict, 시간순 리포트 큐
from datetime import datetime, timezone       # 배포 시각(UTC ISO)

from fastapi import HTTPException

from app.core.config import settings
from app.deployment import domain
from app.deployment.repository import (   # 이름으로 import — 테스트가 이 네임스페이스를 monkeypatch 한다
    generate_presigned_model_download_url,
    get_latest,
    put_latest,
)

# 버전 리포팅 기록 (인메모리 — 서버 재시작 시 초기화, 폴링이 다시 채움)
# 구조: {platform: deque[(리포트 시각 epoch초, version)]} — 시간순이라 앞에서부터 만료 제거.
_reports: dict[str, deque] = defaultdict(deque)


def _prune(platform: str):
    # 윈도우를 벗어난 오래된 리포트를 앞에서부터 제거 (deque는 시간순 append라 앞쪽이 가장 오래됨)
    now = time.time()
    q = _reports[platform]
    while q and not domain.is_active(q[0][0], now):
        q.popleft()


def deploy(platform: str, version: str) -> dict:
    """지정 버전을 latest.json에 기록하는 배포 유스케이스 (롤백 = 과거 버전 재배포)."""
    # mlflow는 배포(어드민)만 쓴다 — 유저 서비스 이미지가 mlflow 없이 뜨도록 지연 import
    import mlflow

    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = mlflow.MlflowClient()

    experiment = client.get_experiment_by_name(f"fitset-{platform}")   # 플랫폼 experiment
    if not experiment:
        raise HTTPException(status_code=404, detail="학습 이력이 없습니다.")

    # search_runs(filter_string=...) : run_name(=version)이 일치하는 run을 찾는다.
    runs = client.search_runs(
        experiment_ids=[experiment.experiment_id],
        filter_string=f"tags.mlflow.runName = '{version}'",
    )
    if not runs:
        raise HTTPException(status_code=404, detail=f"버전 {version}의 학습 결과가 없습니다.")

    run = runs[0]
    deployed_at = datetime.now(timezone.utc).isoformat()   # 배포 시각
    put_latest(platform, {        # latest.json 갱신
        "version": version,
        "modelUrl": domain.model_url(platform, version),   # 경로 규칙은 domain
        "deployedAt": deployed_at,
        "mlflowRunId": run.info.run_id,
    })

    return {
        "deployedVersion": version,
        "platform": platform,
        "deployedAt": deployed_at,
    }


def latest(platform: str, current_version: str | None) -> dict:
    """앱 폴링 유스케이스 — 최신 버전·다운로드 URL 반환 + 버전 리포팅 기록."""
    latest_info = get_latest(platform)           # 배포된 최신 정보(latest.json)
    if not latest_info:
        raise HTTPException(status_code=404, detail="배포된 모델이 없습니다.")

    if current_version:
        _reports[platform].append((time.time(), current_version))   # 폴링 리포팅 기록
        _prune(platform)                                            # 쌓기만 하지 않도록 그때그때 만료 제거

    latest_version = latest_info["version"]
    return {
        "latestVersion": latest_version,
        # latest.json에는 s3:// 정본 경로가 저장돼 있고, 앱에는 임시 서명 HTTPS URL로 내려준다.
        "modelUrl": generate_presigned_model_download_url(latest_info["modelUrl"]),
        "metaUrl": settings.class_mapping_url,   # 클래스 번호와 운동 slug 매핑 테이블(공개 CDN)
        "isUpToDate": current_version == latest_version,   # 앱이 최신인지 여부
    }


def version_stats(platform: str) -> dict:
    """최근 24시간 윈도우의 버전 분포 집계 유스케이스."""
    latest_info = get_latest(platform)
    latest_version = latest_info["version"] if latest_info else None

    _prune(platform)                             # 조회 시점 기준으로 윈도우 밖 리포트 제거
    counts = domain.aggregate_reports(_reports[platform], time.time())   # 집계 규칙은 domain
    total = sum(counts.values()) or 1            # 합(0이면 1로 — 0 나눗셈 방지)

    return {
        "latestVersion": latest_version,
        "totalReports": sum(counts.values()),    # 윈도우 내 전체 리포트 수(분모)
        "stats": [
            {"version": v, "count": c, "ratio": round(c / total, 2)}   # 버전별 리포트 수·비율
            for v, c in counts.most_common()     # 리포트 수 내림차순
        ],
    }
