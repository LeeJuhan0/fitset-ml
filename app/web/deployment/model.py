from collections import defaultdict

from fastapi import APIRouter, Depends
from fastapi import HTTPException

from app.web.deps import validate_platform
from app.core.s3 import get_latest

router = APIRouter()

# 버전 리포팅 집계 (인메모리 — 서버 재시작 시 초기화)
_version_stats: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))


@router.get("/api/v1/{platform}/model/latest")
def model_latest(
    currentVersion: str | None = None,
    platform: str = Depends(validate_platform),
):
    latest = get_latest(platform)
    if not latest:
        raise HTTPException(status_code=404, detail="배포된 모델이 없습니다.")

    if currentVersion:
        _version_stats[platform][currentVersion] += 1

    latest_version = latest["version"]
    return {
        "success": True,
        "code": "200",
        "message": "최신 모델 버전을 조회했습니다.",
        "data": {
            "latestVersion": latest_version,
            "modelUrl": latest["modelUrl"],
            "isUpToDate": currentVersion == latest_version,
        },
    }


@router.get("/api/v1/{platform}/model/version-stats")
def version_stats(platform: str = Depends(validate_platform)):
    latest = get_latest(platform)
    latest_version = latest["version"] if latest else None

    stats = _version_stats[platform]
    total = sum(stats.values()) or 1
    sorted_stats = sorted(stats.items(), key=lambda x: x[1], reverse=True)

    return {
        "success": True,
        "code": "200",
        "message": "버전 분포를 조회했습니다.",
        "data": {
            "latestVersion": latest_version,
            "stats": [
                {"version": v, "count": c, "ratio": round(c / total, 2)}
                for v, c in sorted_stats
            ],
        },
    }
