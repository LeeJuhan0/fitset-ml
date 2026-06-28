from datetime import datetime, timezone

import mlflow
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.web.deps import validate_platform
from app.core.config import settings
from app.core.s3 import get_latest, put_latest

router = APIRouter()


class DeployRequest(BaseModel):
    version: str


@router.post("/api/v1/{platform}/deploy")
def deploy(body: DeployRequest, platform: str = Depends(validate_platform)):
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = mlflow.MlflowClient()

    experiment = client.get_experiment_by_name(f"fitset-{platform}")
    if not experiment:
        raise HTTPException(status_code=404, detail="학습 이력이 없습니다.")

    runs = client.search_runs(
        experiment_ids=[experiment.experiment_id],
        filter_string=f"tags.mlflow.runName = '{body.version}'",
    )
    if not runs:
        raise HTTPException(status_code=404, detail=f"버전 {body.version}의 학습 결과가 없습니다.")

    run = runs[0]
    ext = "mlpackage.zip" if platform == "ios" else "tflite"
    model_path = f"s3://{settings.models_bucket}/{platform}/{body.version}/FitSet.{ext}"

    deployed_at = datetime.now(timezone.utc).isoformat()
    put_latest(platform, {
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
