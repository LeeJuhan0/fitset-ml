# ─────────────────────────────────────────────────────────────────────────────
# deployment 도메인 API(controller) — 배포/최신 모델 조회/버전 분포. 유스케이스는 service에 위임.
# 엔드포인트: POST /deploy, GET /model/latest(앱 폴링), GET /model/version-stats(대시보드)
# ─────────────────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends

from app.deps import validate_platform
from app.deployment import service
from app.deployment.schemas import DeployRequest

router = APIRouter()


@router.post("/api/v1/{platform}/deploy")
def deploy(body: DeployRequest, platform: str = Depends(validate_platform)):
    return {
        "success": True,
        "code": "200",
        "message": "모델을 배포했습니다.",
        "data": service.deploy(platform, body.version),
    }


@router.get("/api/v1/{platform}/model/latest")
def model_latest(
    currentVersion: str | None = None,           # 쿼리 ?currentVersion= (앱의 현재 버전, 선택)
    platform: str = Depends(validate_platform),
):
    return {
        "success": True,
        "code": "200",
        "message": "최신 모델 버전을 조회했습니다.",
        "data": service.latest(platform, currentVersion),
    }


@router.get("/api/v1/{platform}/model/version-stats")
def version_stats(platform: str = Depends(validate_platform)):
    return {
        "success": True,
        "code": "200",
        "message": "버전 분포를 조회했습니다.",
        "data": service.version_stats(platform),
    }
