# ─────────────────────────────────────────────────────────────────────────────
# training 도메인 Service — 학습 시작(Producer–Worker)·진행률·이력 유스케이스 조율.
# 여기(web 프로세스)는 작업을 "시작만" 하고, 실제 학습은 app.worker.trainer가 한다.
# HTTPException을 직접 던지는 것은 계층 순수성보다 단순함을 택한 MVP 트레이드오프.
# ─────────────────────────────────────────────────────────────────────────────
import subprocess   # 워커를 별도 프로세스로 실행
import sys          # 현재 파이썬 실행파일 경로(sys.executable)
import json         # files 리스트를 인자로 넘기려 JSON 직렬화
import tempfile     # 워커 로그 파일을 둘 임시 디렉토리
import pathlib      # 로그 파일 경로 조립

import mlflow
from fastapi import HTTPException

from app.core.config import settings
from app.core.s3 import get_index                  # 인덱스 조회 (검증용)
from app.training import domain
from app.training.repository import next_version   # 버전 채번

# platform → {job_id, run_id, process, version, total_epochs}
_running: dict[str, dict] = {}   # 플랫폼별 진행 중 학습 추적(인메모리 — 재시작 시 사라짐)


def start_training(platform: str, files: list[str], epochs: int, lr: float) -> dict:
    """검증 → 버전 채번 → MLflow run 생성 → trainer 서브프로세스 spawn까지의 유스케이스."""
    if platform in _running and _running[platform]["process"].poll() is None:
        # poll() is None = 프로세스가 아직 실행 중 → 같은 플랫폼 중복 학습 거절
        raise HTTPException(status_code=409, detail="해당 플랫폼 학습이 이미 진행 중입니다.")

    index = get_index(platform)                          # 등록된 파일 목록
    valid = {f["filename"] for f in index["files"]}      # 유효 파일명 집합
    invalid = [f for f in files if f not in valid]       # 요청 중 인덱스에 없는 파일
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

    # 워커의 stdout/stderr를 받아둘 로그 파일(임시 디렉토리)
    log_path = pathlib.Path(tempfile.gettempdir()) / f"trainer_{platform}_{version}.log"
    log_file = open(log_path, "w")

    # subprocess.Popen([...]) : 새 프로세스를 "시작만" 하고 즉시 다음 줄로(블로킹 X).
    #   리스트 = 실행할 명령과 인자. trainer.py의 argparse가 이 인자들을 받는다.
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "app.worker.trainer",   # 현재 파이썬으로 trainer 모듈 실행
            "--platform", platform,
            "--files", json.dumps(files),                 # 리스트 → JSON 문자열
            "--epochs", str(epochs),
            "--lr", str(lr),
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
        "total_epochs": epochs,   # 진행률 분모
    }

    return {"jobId": run_id, "experimentId": exp_id, "version": version, "totalEpochs": epochs}


def get_status(platform: str, job_id: str) -> dict:
    """MLflow run 상태·최신 메트릭 조회 유스케이스."""
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = mlflow.MlflowClient()

    try:
        run = client.get_run(job_id)       # MLflow에서 해당 run 조회
    except Exception:
        raise HTTPException(status_code=404, detail="해당 jobId의 작업이 없습니다.")

    state = run.info.status                # RUNNING/FINISHED/FAILED
    metrics = run.data.metrics             # 워커가 기록한 최신 메트릭 dict
    job = _running.get(platform, {})       # 인메모리 정보(분모 등)
    total = job.get("total_epochs", 0)

    return {
        "status": domain.STATUS_MAP.get(state, state.lower()),   # 상태 표기 규칙은 domain
        "experimentId": run.info.experiment_id,
        "epoch": int(metrics.get("epoch", 0)),         # 현재 에폭
        "totalEpochs": total,                          # 전체 에폭
        "trainLoss": metrics.get("train_loss"),
        "valLoss": metrics.get("val_loss"),
        "valAccuracy": metrics.get("val_accuracy"),
    }


def list_runs(platform: str) -> dict:
    """최근 50개 run 목록 + best run 선정. 데이터 출처는 전적으로 MLflow(별도 DB 없음)."""
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = mlflow.MlflowClient()

    exp = client.get_experiment_by_name(f"fitset-{platform}")   # 플랫폼 experiment
    if not exp:
        return {"runs": []}                # 학습 이력 없음

    # search_runs(experiment_ids, order_by, max_results) : run들을 검색.
    raw = client.search_runs(
        experiment_ids=[exp.experiment_id],
        order_by=["start_time DESC"],   # 최신순
        max_results=50,                 # 최근 50개
    )

    runs = []
    for r in raw:                       # 각 run을 화면용 dict로 가공
        p = r.data.params               # 학습 파라미터(문자열로 저장됨)
        m = r.data.metrics              # 메트릭(float)
        start_ms = r.info.start_time   # 시작 시각(ms epoch)
        end_ms = r.info.end_time       # 종료 시각(없으면 None)
        duration = round((end_ms - start_ms) / 1000) if end_ms else None   # 소요(초)

        runs.append({
            "runId": r.info.run_id,
            "version": r.info.run_name,
            "status": r.info.status,
            "startTime": start_ms,
            "duration": duration,
            "params": {   # 문자열로 저장된 파라미터를 숫자로 복원
                "epochs": int(p["epochs"]) if "epochs" in p else None,
                "lr": float(p["lr"]) if "lr" in p else None,
                "numFiles": len(json.loads(p["files"])) if "files" in p else None,   # files JSON 길이
            },
            "metrics": {
                "trainLoss": m.get("train_loss"),
                "valLoss": m.get("val_loss"),
                "valAccuracy": m.get("val_accuracy"),
                "testAccuracy": m.get("test_accuracy"),
                "f1Macro": m.get("f1_macro"),
                "epoch": int(m.get("epoch", 0)),
            },
        })

    return {"runs": runs, "bestRunId": domain.pick_best_run(runs)}   # 선정 규칙은 domain


def metric_history(run_id: str, metric: str) -> dict:
    """특정 run의 메트릭 step별 시계열 조회."""
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = mlflow.MlflowClient()

    # get_metric_history(run_id, key) : 그 메트릭의 step별 기록 전체를 반환.
    history = client.get_metric_history(run_id, metric)
    return {
        "metric": metric,
        "history": [{"step": h.step, "value": h.value} for h in history],   # (step, value) 시계열
    }
