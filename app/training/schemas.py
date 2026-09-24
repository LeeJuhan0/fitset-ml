from pydantic import computed_field

from app.core.schemas import CamelModel


class TrainRequest(CamelModel):
    """train 바디, files epochs lr"""
    files: list[str]
    epochs: int = 200
    lr: float = 0.001


class TrainStartResponse(CamelModel):
    """train 응답, jobId version totalEpochs"""
    job_id: str
    experiment_id: str
    version: str
    total_epochs: int


class TrainStatusResponse(CamelModel):
    """status 응답, 에폭 진행과 손실"""
    status: str
    experiment_id: str
    epoch: int
    total_epochs: int
    train_loss: float | None = None
    val_loss: float | None = None
    val_accuracy: float | None = None


class RunParams(CamelModel):
    """run 파라미터, epochs lr numFiles"""
    epochs: int | None = None
    lr: float | None = None
    num_files: int | None = None


class RunMetrics(CamelModel):
    """run 지표, loss accuracy f1"""
    train_loss: float | None = None
    val_loss: float | None = None
    val_accuracy: float | None = None
    test_accuracy: float | None = None
    f1_macro: float | None = None
    epoch: int


class RunItem(CamelModel):
    """runs 원소, 버전 상태 시각 지표"""
    run_id: str
    version: str
    status: str
    start_time: int
    end_time: int | None = None
    params: RunParams
    metrics: RunMetrics

    @computed_field
    @property
    def duration(self) -> int | None:
        """소요 초, 종료 전이면 None"""
        if self.end_time is None:
            return None
        return round((self.end_time - self.start_time) / 1000)


class RunsResponse(CamelModel):
    """runs 응답, 목록과 best run"""
    runs: list[RunItem]
    best_run_id: str | None = None


class MetricPoint(CamelModel):
    """메트릭 시계열 점, step value"""
    step: int
    value: float


class MetricHistoryResponse(CamelModel):
    """history 응답, 메트릭 시계열"""
    metric: str
    history: list[MetricPoint]


class JobIdRequest(CamelModel):
    """?jobId= 쿼리, start_training 이 준 run_id"""
    job_id: str


class MetricRequest(CamelModel):
    """?metric= 쿼리, 기본 val_loss"""
    metric: str = "val_loss"
