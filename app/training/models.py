from pydantic import AwareDatetime
from sqlalchemy import Text
from sqlmodel import Field, Relationship, SQLModel
from sqlmodel.sql.sqltypes import UTCDateTime

from app.core.models import CREATED_AT, UPDATED_AT, Platform


class TrainingRun(SQLModel, table=True):
    """분류 학습 이력, MLflow run 과 1:1, 프로세스 종료 판정 결과"""
    __tablename__ = "training_runs"

    id: int = Field(default=None, primary_key=True)
    mlflow_run_id: str = Field(max_length=64, unique=True, description="jobId, MLflow run id")
    version: str = Field(max_length=32)
    status: str = Field(default="running", max_length=16, index=True, description="running, completed, failed")
    epochs: int
    lr: float
    num_files: int
    error: str | None = Field(default=None, sa_type=Text, description="실패 사유, 종료 코드와 로그 끝부분")
    finished_at: AwareDatetime | None = Field(default=None, sa_type=UTCDateTime)

    platform_id: int = Field(foreign_key="platforms.id", index=True)
    platform: Platform = Relationship(sa_relationship_kwargs={"lazy": "joined"})

    created_at: AwareDatetime = Field(**CREATED_AT)
    updated_at: AwareDatetime = Field(**UPDATED_AT)

    def __str__(self):
        """표시 문자열"""
        return f"{self.platform}/{self.version} ({self.status})"
