# ─────────────────────────────────────────────────────────────────────────────
# 배포 도메인 API — main.py가 deploy_router로 등록. 엔드포인트: POST /deploy
# "배포" = 특정 버전을 latest.json에 기록하는 것. 앱은 그걸 폴링해 새 모델을 받는다(push 없음).
# ─────────────────────────────────────────────────────────────────────────────
from datetime import datetime, timezone   # 배포 시각(UTC ISO)

import mlflow
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.web.deps import validate_platform
from app.core.config import settings
from app.core.s3 import get_latest, put_latest   # latest.json 읽기/쓰기

router = APIRouter()


class DeployRequest(BaseModel):   # POST /deploy 바디
    version: str                  # 배포할 버전(예: v1.3)


@router.post("/api/v1/{platform}/deploy")
def deploy(body: DeployRequest, platform: str = Depends(validate_platform)):
    # body.version: 배포 대상 버전,  platform: 경로 검증값
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = mlflow.MlflowClient()

    experiment = client.get_experiment_by_name(f"fitset-{platform}")   # 플랫폼 experiment
    if not experiment:
        raise HTTPException(status_code=404, detail="학습 이력이 없습니다.")

    # search_runs(filter_string=...) : run_name(=version)이 일치하는 run을 찾는다.
    runs = client.search_runs(
        experiment_ids=[experiment.experiment_id],
        filter_string=f"tags.mlflow.runName = '{body.version}'",
    )
    if not runs:
        raise HTTPException(status_code=404, detail=f"버전 {body.version}의 학습 결과가 없습니다.")

    run = runs[0]
    ext = "mlpackage.zip" if platform == "ios" else "tflite"   # 플랫폼별 모델 확장자
    model_path = f"s3://{settings.models_bucket}/{platform}/{body.version}/FitSet.{ext}"   # 모델 S3 위치

    deployed_at = datetime.now(timezone.utc).isoformat()   # 배포 시각
    put_latest(platform, {        # latest.json 갱신 → s3.put_latest
        "version": body.version,
        "modelUrl": model_path,
        "deployedAt": deployed_at,
        "mlflowRunId": run.info.run_id,
    })

    return {
        "success": True,
        "code": "200",
        "message": "모델을 배포했습니다.",
        "data": {
            "deployedVersion": body.version,
            "platform": platform,
            "deployedAt": deployed_at,
        },
    }
