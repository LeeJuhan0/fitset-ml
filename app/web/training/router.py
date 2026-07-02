# ─────────────────────────────────────────────────────────────────────────────
# 학습 도메인 API — main.py가 train_router로 등록.
# 엔드포인트: POST /train(워커 spawn, 202), GET /train/status(진행률)
# Producer–Worker 패턴: 여기(web)는 작업을 "시작만" 하고, 실제 학습은 app.worker.trainer가 한다.
# ─────────────────────────────────────────────────────────────────────────────
import subprocess   # 워커를 별도 프로세스로 실행
import sys          # 현재 파이썬 실행파일 경로(sys.executable)
import json         # files 리스트를 인자로 넘기려 JSON 직렬화

import mlflow
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.web.deps import validate_platform
from app.core.config import settings
from app.core.s3 import get_index, next_version   # 인덱스 조회, 다음 버전 채번

router = APIRouter()

# platform → {job_id, run_id, process, version, total_epochs}
_running: dict[str, dict] = {}   # 플랫폼별 진행 중 학습 추적(인메모리 — 재시작 시 사라짐)


class TrainRequest(BaseModel):   # POST /train 바디 스키마
    files: list[str]             # 학습에 쓸 파일명 목록(필수)
    epochs: int = 200            # 에폭 수(기본 200)
    lr: float = 0.001            # 학습률(기본 0.001)


@router.post("/api/v1/{platform}/train", status_code=202)
def start_training(body: TrainRequest, platform: str = Depends(validate_platform)):
    # body: 학습 파라미터, platform: 경로 검증값. status_code=202 → 성공 시 "접수됨"
    if platform in _running and _running[platform]["process"].poll() is None:
        # poll() is None = 프로세스가 아직 실행 중 → 같은 플랫폼 중복 학습 거절
        raise HTTPException(status_code=409, detail="해당 플랫폼 학습이 이미 진행 중입니다.")

    index = get_index(platform)                          # 등록된 파일 목록
    valid = {f["filename"] for f in index["files"]}      # 유효 파일명 집합
    invalid = [f for f in body.files if f not in valid]  # 요청 중 인덱스에 없는 파일
    if invalid:
        raise HTTPException(status_code=400, detail=f"존재하지 않는 파일: {invalid}")

    version = next_version(platform)                     # 이번 학습 산출물 버전(예: v1.3)

    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)   # MLflow 서버 주소 설정
    # MlflowClient로 생성 → 상태가 RUNNING으로 유지됨 (end_run 호출 안 함)
    client = mlflow.MlflowClient()                          # 저수준 MLflow 클라이언트
    exp = client.get_experiment_by_name(f"fitset-{platform}")   # 플랫폼별 experiment 조회
    if exp is None:
        exp_id = client.create_experiment(f"fitset-{platform}")  # 없으면 생성
    else:
        exp_id = exp.experiment_id
    run = client.create_run(experiment_id=exp_id, run_name=version)   # RUNNING 상태 run 생성
    run_id = run.info.run_id                                # 이 run_id가 곧 jobId

    import tempfile, pathlib
    # 워커의 stdout/stderr를 받아둘 로그 파일(임시 디렉토리)
    log_path = pathlib.Path(tempfile.gettempdir()) / f"trainer_{platform}_{version}.log"
    log_file = open(log_path, "w")

    # subprocess.Popen([...]) : 새 프로세스를 "시작만" 하고 즉시 다음 줄로(블로킹 X).
    #   리스트 = 실행할 명령과 인자. trainer.py의 argparse가 이 인자들을 받는다.
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "app.worker.trainer",   # 현재 파이썬으로 trainer 모듈 실행
            "--platform", platform,
            "--files", json.dumps(body.files),            # 리스트 → JSON 문자열
            "--epochs", str(body.epochs),
            "--lr", str(body.lr),
            "--run-id", run_id,                           # 워커가 이 run에 이어서 기록
            "--version", version,
        ],
        stdout=log_file,
        stderr=log_file,
    )

    _running[platform] = {        # 진행 상태 등록(중복검사·status 조회용)
        "job_id": run_id,
        "process": proc,          # Popen 객체(poll()로 살아있는지 확인)
        "version": version,
        "total_epochs": body.epochs,   # 진행률 분모
    }

    return {                      # 완료를 기다리지 않고 즉시 반환
        "success": True,
        "code": "202",
        "message": "학습을 시작했습니다.",
        "data": {"jobId": run_id, "experimentId": exp_id, "version": version, "totalEpochs": body.epochs},
    }


@router.get("/api/v1/{platform}/train/status")
def train_status(jobId: str, platform: str = Depends(validate_platform)):
    # jobId: 쿼리 ?jobId= (start_training이 준 run_id). platform: 경로 검증값.
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = mlflow.MlflowClient()

    try:
        run = client.get_run(jobId)        # MLflow에서 해당 run 조회
    except Exception:
        raise HTTPException(status_code=404, detail="해당 jobId의 작업이 없습니다.")

    state = run.info.status                # RUNNING/FINISHED/FAILED
    metrics = run.data.metrics             # 워커가 기록한 최신 메트릭 dict
    job = _running.get(platform, {})       # 인메모리 정보(분모 등)
    total = job.get("total_epochs", 0)

    status_map = {"RUNNING": "running", "FINISHED": "completed", "FAILED": "failed"}   # MLflow 상태 → 앱 표기

    return {
        "success": True,
        "code": "200",
        "message": "학습 진행률을 조회했습니다.",
        "data": {
            "status": status_map.get(state, state.lower()),
            "experimentId": run.info.experiment_id,
            "epoch": int(metrics.get("epoch", 0)),         # 현재 에폭
            "totalEpochs": total,                          # 전체 에폭
            "trainLoss": metrics.get("train_loss"),
            "valLoss": metrics.get("val_loss"),
            "valAccuracy": metrics.get("val_accuracy"),
        },
    }
