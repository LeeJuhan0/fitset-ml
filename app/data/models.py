from typing import TYPE_CHECKING, Optional

from pydantic import AwareDatetime, computed_field
from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from app.core.models import CREATED_AT, UPDATED_AT, WIRE, Device, Exercise, Platform

if TYPE_CHECKING:
    from app.phase.models import CollectFile, PhaseModel


class DatasetFileBase(SQLModel):
    """dataset_files 공통 열, 테이블 모델과 Read 모델이 공유"""
    filename: str = Field(max_length=128, description="{CLASS}_{deviceId}_{NNNN}.csv 또는 .parquet")
    class_name: str = Field(max_length=64, index=True, description="운동 종목 라벨, CLASSES 원소")
    bucket: str = Field(max_length=64, description="실물 버킷 fitset-dataset")
    s3_key: str = Field(max_length=256, description="{platform}/raw/{index}_{class}/{filename}, 구 데이터는 raw/{class}"),
    uploaded: bool = Field(default=False, description="presigned PUT 완료 확정 여부")
    phase_labeled: bool = Field(default=False, description="phase 열 보유, 렙카운팅 모델 학습 후보")
    trained_in_version: str | None = Field(default=None, max_length=32, description="마지막으로 분류 학습에 쓰인 모델 버전")


class DatasetFile(DatasetFileBase, table=True):
    """학습 데이터셋 목록, fitset-dataset 버킷 실물, 분류·렙카운팅 학습 원천"""
    __tablename__ = "dataset_files"
    __table_args__ = (UniqueConstraint("platform_id", "filename", name="uq_dataset_platform_filename"),)

    id: int = Field(default=None, primary_key=True)

    platform_id: int = Field(foreign_key="platforms.id", index=True)
    platform: Platform = Relationship(
        back_populates="dataset_files",
        sa_relationship_kwargs={"lazy": "joined"},
    )

    device_fk: int = Field(foreign_key="devices.id", index=True)
    device: Device = Relationship(
        back_populates="dataset_files",
        sa_relationship_kwargs={"lazy": "joined"},
    )

    exercise_fk: int | None = Field(default=None, foreign_key="exercises.id", index=True)
    exercise: Optional[Exercise] = Relationship(
        back_populates="dataset_files",
        sa_relationship_kwargs={"lazy": "joined"},
    )

    collect_file: Optional["CollectFile"] = Relationship(
        back_populates="dataset_file",
        sa_relationship_kwargs={"uselist": False, "lazy": "noload"},
    )
    phase_models: list["PhaseModel"] = Relationship(
        back_populates="files",
        sa_relationship_kwargs={"secondary": "phase_model_files", "lazy": "noload"},
    )

    created_at: AwareDatetime = Field(**CREATED_AT)
    updated_at: AwareDatetime = Field(**UPDATED_AT)

    def __str__(self):
        """표시 문자열"""
        return f"{self.platform}/{self.class_name}/{self.filename}"


class DatasetFileRead(DatasetFileBase):
    """GET /data 응답 원소, camelCase, class alias"""
    model_config = WIRE
    id: int
    device_id: str
    created_at: AwareDatetime

    @computed_field
    @property
    def is_trained(self) -> bool:
        """분류 학습에 한 번이라도 쓰였는지"""
        return self.trained_in_version is not None

    @computed_field
    @property
    def format(self) -> str:
        """파일 형식, 확장자에서 유도, parquet 또는 csv"""
        return "parquet" if self.filename.endswith(".parquet") else "csv"

    @classmethod
    def from_row(cls, r: DatasetFile) -> "DatasetFileRead":
        """테이블 행 변환, device_id 는 관계에서"""
        return cls(device_id=r.device.device_id, **r.model_dump())
