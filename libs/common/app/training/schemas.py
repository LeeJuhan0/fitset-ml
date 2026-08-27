# ─────────────────────────────────────────────────────────────────────────────
# training 도메인 요청/응답 스키마 (Pydantic DTO).
# ─────────────────────────────────────────────────────────────────────────────
from pydantic import BaseModel

from app.core.schemas import CamelModel


class TrainRequest(BaseModel):   # POST /train 바디 스키마
    files: list[str]             # 학습에 쓸 파일명 목록(필수)
    epochs: int = 200            # 에폭 수(기본 200)
    lr: float = 0.001            # 학습률(기본 0.001)


class TrainStartData(CamelModel):
    # POST /train(202) 응답 data
    job_id: str                  # MLflow run_id — status 조회 키
    experiment_id: str
    version: str                 # 이번 학습 산출물 버전(예: v1.3)
    total_epochs: int


class TrainStatusData(CamelModel):
    # GET /train/status 응답 data
    status: str                  # running/completed/failed (표기 규칙은 domain.STATUS_MAP)
    experiment_id: str
    epoch: int                   # 현재 에폭
    total_epochs: int
    train_loss: float | None = None   # 아직 기록 전이면 None
    val_loss: float | None = None
    val_accuracy: float | None = None


class RunParams(CamelModel):
    # run 목록 항목의 학습 파라미터 (기록 안 된 항목은 None)
    epochs: int | None = None
    lr: float | None = None
    num_files: int | None = None


class RunMetrics(CamelModel):
    # run 목록 항목의 메트릭 (기록 안 된 항목은 None)
    train_loss: float | None = None
    val_loss: float | None = None
    val_accuracy: float | None = None
    test_accuracy: float | None = None
    f1_macro: float | None = None
    epoch: int


class RunItem(CamelModel):
    # GET /runs 응답의 runs 원소 하나
    run_id: str
    version: str                 # run_name(=모델 버전)
    status: str                  # RUNNING/FINISHED/FAILED (MLflow 원값)
    start_time: int              # 시작 시각(ms epoch)
    duration: int | None = None  # 소요(초) — 진행 중이면 None
    params: RunParams
    metrics: RunMetrics


class RunsData(CamelModel):
    # GET /runs 응답 data
    runs: list[RunItem]
    best_run_id: str | None = None   # 선정 규칙은 domain.pick_best_run


class MetricPoint(CamelModel):
    # 메트릭 시계열의 한 점
    step: int
    value: float


class MetricHistoryData(CamelModel):
    # GET /runs/{run_id}/history 응답 data
    metric: str
    history: list[MetricPoint]
