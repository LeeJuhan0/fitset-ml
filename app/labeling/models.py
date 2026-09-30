from typing import Any, Optional

from pydantic import AwareDatetime, computed_field
from sqlalchemy import JSON, Double, Text, UniqueConstraint
from sqlalchemy.ext.hybrid import hybrid_property
from sqlmodel import Field, Relationship, SQLModel

from app.core.models import CREATED_AT, ENTITY, UPDATED_AT, WIRE, Device, Exercise, Platform, UTCDateTime6
from app.core.utils import utcnow
from app.labeling.enums import CollectStatus
from app.data.models import DatasetFile, DatasetFileRead


class PhaseLabelBase(SQLModel):
    """phase_labels 공통 열, labeled 버킷 객체 3종과 요약"""
    data_bucket: str = Field(max_length=64, description="phase 열이 붙은 parquet 버킷 fitset-collect-labeled")
    data_key: str = Field(max_length=256, description="{platform}/{index}_{class}/{stem}.parquet")
    video_bucket: str = Field(max_length=64, description="복사된 영상 버킷")
    video_key: str = Field(max_length=256, description="{platform}/{index}_{class}/{stem}.mov")
    pose_key: str = Field(max_length=256, description="프레임별 관절 33개와 phase JSON")
    phase_summary: dict[str, Any] = Field(default_factory=dict, sa_type=JSON, description="frames, fps, detectedFraction, rowPhaseCounts")
    labeled_at: AwareDatetime = Field(default_factory=utcnow, sa_type=UTCDateTime6, description="라벨링 완료 시각")


class PhaseLabel(PhaseLabelBase, table=True):
    """구간 라벨 결과, collect_files 와 1:1"""
    __tablename__ = "phase_labels"

    id: int = Field(default=None, primary_key=True)

    collect_file_id: int = Field(foreign_key="collect_files.id", unique=True)
    collect_file: "CollectFile" = Relationship(
        back_populates="label",
        sa_relationship_kwargs={"lazy": "joined"},
    )

    created_at: AwareDatetime = Field(**CREATED_AT)
    updated_at: AwareDatetime = Field(**UPDATED_AT)

    def __str__(self):
        """표시 문자열"""
        return f"label {self.data_bucket}/{self.data_key}"


class PhaseLabelRead(PhaseLabelBase):
    """라벨 결과 응답, CollectFileRead.label"""
    model_config = WIRE

    @computed_field
    @property
    def rep_count_estimate(self) -> int | None:
        """렙 수 추정, 요약의 repCount"""
        return self.phase_summary.get("repCount")

    @computed_field
    @property
    def has_phase(self) -> bool:
        """0 1 구간 라벨 존재 여부, 규칙 없으면 관절만"""
        return bool(self.phase_summary.get("hasPhase"))


class CollectFileBase(SQLModel):
    """collect_files 공통 열, 원본 객체 위치와 상태"""
    model_config = ENTITY
    filename: str = Field(max_length=128, description="{CLASS}_{deviceId}_{NNNN}.csv, 영상은 같은 stem 의 .mov")
    class_name: str = Field(max_length=64, index=True, description="운동 종목 라벨")
    csv_bucket: str = Field(max_length=64, description="IMU CSV 착지 버킷 fitset-collect-imu")
    csv_key: str = Field(max_length=256, description="{platform}/{index}_{class}/{filename}")
    video_bucket: str = Field(max_length=64, description="영상 착지 버킷 fitset-collect-video")
    video_key: str = Field(max_length=256, description="{platform}/{index}_{class}/{stem}.mov")
    uploaded: bool = Field(default=False, description="CSV, 영상 두 PUT 완료 확정 여부")
    video_start: float | None = Field(default=None, sa_type=Double, description="영상 첫 프레임 unix 초, IMU 행과 프레임 대응 기준")
    rows: int | None = Field(default=None, description="CSV 데이터 행 수")
    status: str = Field(default="pending", max_length=16, index=True, description="pending, labeling, labeled, failed")
    error: str | None = Field(default=None, sa_type=Text, description="워커 실패 사유")
    promoted_at: AwareDatetime | None = Field(default=None, sa_type=UTCDateTime6, description="dataset_files 승격 시각")

    @hybrid_property
    def is_labeling(self) -> bool:
        """워커 처리 중 여부"""
        return self.status in [CollectStatus.LABELING, CollectStatus.LABELING.value]

    @is_labeling.expression
    def is_labeling(cls):
        """쿼리 조건식, status IN"""
        return cls.status.in_([CollectStatus.LABELING.value])

    @hybrid_property
    def is_labeled(self) -> bool:
        """라벨링 완료 여부"""
        return self.status in [CollectStatus.LABELED, CollectStatus.LABELED.value]

    @is_labeled.expression
    def is_labeled(cls):
        """쿼리 조건식, status IN"""
        return cls.status.in_([CollectStatus.LABELED.value])

    @hybrid_property
    def is_labelable(self) -> bool:
        """라벨링 시작 가능 상태, 대기 또는 실패"""
        return self.status in [CollectStatus.PENDING, CollectStatus.PENDING.value, CollectStatus.FAILED, CollectStatus.FAILED.value]

    @is_labelable.expression
    def is_labelable(cls):
        """쿼리 조건식, status IN"""
        return cls.status.in_([CollectStatus.PENDING.value, CollectStatus.FAILED.value])


class CollectFile(CollectFileBase, table=True):
    """수집앱 IMU+영상 쌍, 라벨링 대상, 승격 시 dataset_file 연결"""
    __tablename__ = "collect_files"
    __table_args__ = (UniqueConstraint("platform_id", "filename", name="uq_collect_platform_filename"),)

    id: int = Field(default=None, primary_key=True)

    platform_id: int = Field(foreign_key="platforms.id", index=True)
    platform: Platform = Relationship(
        back_populates="collect_files",
        sa_relationship_kwargs={"lazy": "joined"},
    )

    device_fk: int = Field(foreign_key="devices.id", index=True)
    device: Device = Relationship(
        back_populates="collect_files",
        sa_relationship_kwargs={"lazy": "joined"},
    )

    exercise_fk: int | None = Field(default=None, foreign_key="exercises.id", index=True)
    exercise: Optional[Exercise] = Relationship(
        back_populates="collect_files",
        sa_relationship_kwargs={"lazy": "joined"},
    )

    label: Optional[PhaseLabel] = Relationship(
        back_populates="collect_file",
        sa_relationship_kwargs={"uselist": False, "lazy": "joined"},
    )

    dataset_file_id: int | None = Field(default=None, foreign_key="dataset_files.id", unique=True)
    dataset_file: Optional[DatasetFile] = Relationship(
        back_populates="collect_file",
        sa_relationship_kwargs={"lazy": "joined"},
    )

    created_at: AwareDatetime = Field(**CREATED_AT)
    updated_at: AwareDatetime = Field(**UPDATED_AT)

    def __str__(self):
        """표시 문자열"""
        return f"{self.platform}/{self.class_name}/{self.filename} ({self.status})"


class CollectFileRead(CollectFileBase):
    """GET /phase/files 응답 원소, label 있으면 완료, dataset_file 있으면 승격됨"""
    model_config = WIRE
    device_id: str
    created_at: AwareDatetime
    label: Optional[PhaseLabelRead] = None
    dataset_file: Optional[DatasetFileRead] = None

    @computed_field
    @property
    def can_label(self) -> bool:
        """라벨링 시작 가능, 업로드 완료·진행 중 아님, 완료 파일은 재라벨"""
        return self.uploaded and not self.is_labeling

    @computed_field
    @property
    def can_promote(self) -> bool:
        """승격 가능, 업로드 완료·미승격 또는 복사 중단, 라벨은 선택"""
        return self.uploaded and (self.dataset_file is None or not self.dataset_file.uploaded)

    @classmethod
    def from_row(cls, r: CollectFile) -> "CollectFileRead":
        """테이블 행 변환, label, dataset_file 관계 포함"""
        label = PhaseLabelRead(**r.label.model_dump()) if r.label is not None else None
        dataset = DatasetFileRead.from_row(r.dataset_file) if r.dataset_file is not None else None
        return cls(device_id=r.device.device_id, label=label, dataset_file=dataset, **r.model_dump())
