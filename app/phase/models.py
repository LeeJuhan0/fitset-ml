from typing import Any, Optional

from pydantic import AwareDatetime, computed_field
from sqlalchemy import JSON, Double, Text, UniqueConstraint
from sqlalchemy.ext.hybrid import hybrid_property
from sqlmodel import Field, Relationship, SQLModel

from app.core.models import CREATED_AT, ENTITY, UPDATED_AT, WIRE, Exercise, Platform, UTCDateTime6
from app.phase.enums import PhaseModelStatus
from app.data.models import DatasetFile


class PhaseModelFile(SQLModel, table=True):
    """렙카운팅 모델 학습에 쓰인 파일, phase_models N:M dataset_files"""
    __tablename__ = "phase_model_files"

    phase_model_id: int = Field(foreign_key="phase_models.id", primary_key=True)
    dataset_file_id: int = Field(foreign_key="dataset_files.id", primary_key=True)


class PhaseModelBase(SQLModel):
    """phase_models 공통 열, 종목별 렙카운팅(0 1 2) 모델 산출물 위치"""
    model_config = ENTITY
    class_name: str = Field(max_length=64, index=True, description="종목, 각도 규칙이 있는 종목")
    version: str = Field(max_length=32, description="종목 안에서 v{major}.{minor}")
    status: str = Field(default="training", max_length=16, index=True, description="training, completed, failed")
    bucket: str = Field(max_length=64, description="fitset-phase-models")
    pt_key: str | None = Field(default=None, max_length=256, description="{platform}/{class}/{version}/FitSetPhase.pt")
    onnx_key: str | None = Field(default=None, max_length=256, description="FitSetPhase.onnx")
    mlpackage_key: str | None = Field(default=None, max_length=256, description="FitSetPhase.mlpackage.zip")
    meta_key: str | None = Field(default=None, max_length=256, description="meta.json, mean std window classes")
    window: int = Field(default=50, description="입력 윈도우 행 수, 0.5초")
    stride: int = Field(default=5, description="학습 윈도우 stride 행 수")
    epochs: int = Field(default=20)
    lr: float = Field(default=0.001, sa_type=Double, description="학습률")
    num_files: int = Field(default=0, description="학습에 쓴 dataset_files 수")
    metrics: dict[str, Any] = Field(default_factory=dict, sa_type=JSON, description="acc, f1, macro_f1, count_mae, per_file")
    mlflow_run_id: str | None = Field(default=None, max_length=64)
    error: str | None = Field(default=None, sa_type=Text, description="워커 실패 사유")
    deployed_at: AwareDatetime | None = Field(default=None, sa_type=UTCDateTime6, description="배포 시각, 종목마다 하나만 값 있음")

    @hybrid_property
    def is_training(self) -> bool:
        """학습 진행 중 여부"""
        return self.status in [PhaseModelStatus.TRAINING, PhaseModelStatus.TRAINING.value]

    @is_training.expression
    def is_training(cls):
        """쿼리 조건식, status IN"""
        return cls.status.in_([PhaseModelStatus.TRAINING.value])

    @hybrid_property
    def is_completed(self) -> bool:
        """산출물 사용 가능 여부"""
        return self.status in [PhaseModelStatus.COMPLETED, PhaseModelStatus.COMPLETED.value]

    @is_completed.expression
    def is_completed(cls):
        """쿼리 조건식, status IN"""
        return cls.status.in_([PhaseModelStatus.COMPLETED.value])


class PhaseModel(PhaseModelBase, table=True):
    """종목별 렙카운팅 모델 버전, pt onnx coreml 산출물 목록"""
    __tablename__ = "phase_models"
    __table_args__ = (UniqueConstraint("platform_id", "class_name", "version", name="uq_phase_model_version"),)

    id: int = Field(default=None, primary_key=True)

    platform_id: int = Field(foreign_key="platforms.id", index=True)
    platform: Platform = Relationship(
        back_populates="phase_models",
        sa_relationship_kwargs={"lazy": "joined"},
    )

    exercise_fk: int | None = Field(default=None, foreign_key="exercises.id", index=True)
    exercise: Optional[Exercise] = Relationship(
        back_populates="phase_models",
        sa_relationship_kwargs={"lazy": "joined"},
    )

    files: list[DatasetFile] = Relationship(
        back_populates="phase_models",
        link_model=PhaseModelFile,
        sa_relationship_kwargs={"lazy": "noload"},
    )

    created_at: AwareDatetime = Field(**CREATED_AT)
    updated_at: AwareDatetime = Field(**UPDATED_AT)

    def __str__(self):
        """표시 문자열"""
        return f"{self.platform}/{self.class_name}/{self.version} ({self.status})"


class PhaseModelRead(PhaseModelBase):
    """GET /phase/models 응답 원소"""
    model_config = WIRE
    id: int
    platform: str
    created_at: AwareDatetime

    @computed_field
    @property
    def can_download(self) -> bool:
        """다운로드 가능, completed 이고 pt 키 있음"""
        return self.is_completed and self.pt_key is not None

    @classmethod
    def from_row(cls, r: PhaseModel) -> "PhaseModelRead":
        """테이블 행 변환, platform 은 이름으로"""
        return cls(platform=r.platform.name, **r.model_dump())
