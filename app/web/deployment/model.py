# ─────────────────────────────────────────────────────────────────────────────
# 모델 조회 도메인 API — main.py가 model_router로 등록.
# 엔드포인트: GET /model/latest(앱 폴링용), GET /model/version-stats(대시보드용)
# 앱이 /model/latest를 폴링할 때 보낸 currentVersion을 모아 버전 분포를 집계한다.
# ─────────────────────────────────────────────────────────────────────────────
from collections import defaultdict   # 자동 0 초기화 dict

from fastapi import APIRouter, Depends
from fastapi import HTTPException

from app.web.deps import validate_platform
from app.core.s3 import get_latest   # latest.json 읽기

router = APIRouter()

# 버전 리포팅 집계 (인메모리 — 서버 재시작 시 초기화)
# 구조: {platform: {version: count}} — 없는 키 접근 시 0부터 시작.
_version_stats: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))


@router.get("/api/v1/{platform}/model/latest")
def model_latest(
    currentVersion: str | None = None,           # 쿼리 ?currentVersion= (앱의 현재 버전, 선택)
    platform: str = Depends(validate_platform),  # 경로 검증값
):
    latest = get_latest(platform)                # 배포된 최신 정보(latest.json)
    if not latest:
        raise HTTPException(status_code=404, detail="배포된 모델이 없습니다.")

    if currentVersion:
        _version_stats[platform][currentVersion] += 1   # 폴링 리포팅 집계(버전별 카운트)

    latest_version = latest["version"]
    return {
        "success": True,
        "code": "200",
        "message": "최신 모델 버전을 조회했습니다.",
        "data": {
            "latestVersion": latest_version,
            "modelUrl": latest["modelUrl"],
            "isUpToDate": currentVersion == latest_version,   # 앱이 최신인지 여부
        },
    }


@router.get("/api/v1/{platform}/model/version-stats")
def version_stats(platform: str = Depends(validate_platform)):
    latest = get_latest(platform)
    latest_version = latest["version"] if latest else None

    stats = _version_stats[platform]             # {version: count}
    total = sum(stats.values()) or 1             # 합(0이면 1로 — 0 나눗셈 방지)
    sorted_stats = sorted(stats.items(), key=lambda x: x[1], reverse=True)   # 카운트 내림차순

    return {
        "success": True,
        "code": "200",
        "message": "버전 분포를 조회했습니다.",
        "data": {
            "latestVersion": latest_version,
            "stats": [
                {"version": v, "count": c, "ratio": round(c / total, 2)}   # 버전별 비율
                for v, c in sorted_stats
            ],
        },
    }
