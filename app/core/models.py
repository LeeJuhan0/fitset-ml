from typing import TYPE_CHECKING, Optional

from pydantic import AwareDatetime, ConfigDict
from sqlalchemy import UniqueConstraint, func
from sqlalchemy.ext.hybrid import hybrid_property
from sqlmodel import Field, Relationship, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.sql.sqltypes import UTCDateTime

from app.core.utils import utcnow, wire_alias

if TYPE_CHECKING:
    from app.data.models import DatasetFile
    from app.phase.models import CollectFile, PhaseModel


ENTITY = ConfigDict(ignored_types=(hybrid_property,))
WIRE = ConfigDict(alias_generator=wire_alias, populate_by_name=True, ignored_types=(hybrid_property,))

CREATED_AT = dict(
    default=None, nullable=False, sa_type=UTCDateTime,
    sa_column_kwargs={"server_default": func.now()},
)
UPDATED_AT = dict(
    default=None, nullable=False, sa_type=UTCDateTime,
    sa_column_kwargs={"server_default": func.now(), "onupdate": utcnow},
)


class Platform(SQLModel, table=True):
    """플랫폼 기준 테이블, ios, android, 기기와 파일 3종의 부모"""
    __tablename__ = "platforms"

    id: int = Field(default=None, primary_key=True)
    name: str = Field(max_length=16, unique=True, index=True, description="ios 또는 android")

    devices: list["Device"] = Relationship(
        back_populates="platform",
        sa_relationship_kwargs={"lazy": "noload"},
    )
    dataset_files: list["DatasetFile"] = Relationship(
        back_populates="platform",
        sa_relationship_kwargs={"lazy": "noload"},
    )
    collect_files: list["CollectFile"] = Relationship(
        back_populates="platform",
        sa_relationship_kwargs={"lazy": "noload"},
    )
    phase_models: list["PhaseModel"] = Relationship(
        back_populates="platform",
        sa_relationship_kwargs={"lazy": "noload"},
    )

    created_at: AwareDatetime = Field(**CREATED_AT)

    def __str__(self):
        """표시 문자열"""
        return self.name


class Device(SQLModel, table=True):
    """수집 기기, 파일명 채번 주인, 플랫폼 안에서 유일"""
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("platform_id", "device_id", name="uq_device_platform_device"),)

    id: int = Field(default=None, primary_key=True)
    device_id: str = Field(max_length=64, index=True, description="앱이 보내는 기기 식별자")

    platform_id: int = Field(foreign_key="platforms.id", index=True)
    platform: Platform = Relationship(
        back_populates="devices",
        sa_relationship_kwargs={"lazy": "joined"},
    )

    dataset_files: list["DatasetFile"] = Relationship(
        back_populates="device",
        sa_relationship_kwargs={"lazy": "noload"},
    )
    collect_files: list["CollectFile"] = Relationship(
        back_populates="device",
        sa_relationship_kwargs={"lazy": "noload"},
    )

    created_at: AwareDatetime = Field(**CREATED_AT)

    def __str__(self):
        """표시 문자열"""
        return f"{self.platform}/{self.device_id}"


class ExerciseBase(SQLModel):
    """exercises 공통 열, 모델 출력 인덱스와 백엔드 slug 매핑"""
    index: int = Field(unique=True, description="모델 출력 인덱스, 0~13 은 배포 모델 고정")
    class_name: str = Field(max_length=64, unique=True, description="CLASSES 라벨, slug 대문자 스네이크")
    slug: str = Field(max_length=64, unique=True, description="백엔드 exercises API slug")
    name: str = Field(max_length=128, description="한글 이름")
    exercise_id: str | None = Field(default=None, max_length=36, description="백엔드 exercise UUID")
    phase_supported: bool = Field(default=False, description="구간 라벨링, 렙카운팅 모델 지원 여부, angle_joints 유무로 결정")
    angle_joints: str | None = Field(default=None, max_length=32, description="각도를 만드는 관절 3개, 예 hip,kn,an")
    down_is_decreasing: bool | None = Field(default=None, description="각도가 줄어드는 방향이 내려감인지")


class Exercise(ExerciseBase, table=True):
    """운동 종목 마스터, class-mapping.json 시드, 파일과 모델이 참조"""
    __tablename__ = "exercises"

    id: int = Field(default=None, primary_key=True)

    dataset_files: list["DatasetFile"] = Relationship(
        back_populates="exercise",
        sa_relationship_kwargs={"lazy": "noload"},
    )
    collect_files: list["CollectFile"] = Relationship(
        back_populates="exercise",
        sa_relationship_kwargs={"lazy": "noload"},
    )
    phase_models: list["PhaseModel"] = Relationship(
        back_populates="exercise",
        sa_relationship_kwargs={"lazy": "noload"},
    )

    created_at: AwareDatetime = Field(**CREATED_AT)
    updated_at: AwareDatetime = Field(**UPDATED_AT)

    def __str__(self):
        """표시 문자열"""
        return f"{self.index} {self.class_name} ({self.slug})"


class ExerciseRead(ExerciseBase):
    """GET /exercises 응답 원소"""
    model_config = WIRE
    id: int


async def ensure_platform(s: AsyncSession, name: str) -> Platform:
    """플랫폼 행 조회, 없으면 생성, flush"""
    row = (await s.exec(select(Platform).where(Platform.name == name))).first()
    if row is not None:
        return row
    row = Platform(name=name)
    s.add(row)
    await s.flush()
    return row


async def ensure_device(s: AsyncSession, platform: Platform, device_id: str) -> Device:
    """기기 행 조회, 없으면 생성, flush"""
    row = (await s.exec(select(Device).where(Device.platform_id == platform.id, Device.device_id == device_id))).first()
    if row is not None:
        return row
    row = Device(platform=platform, device_id=device_id)
    s.add(row)
    await s.flush()
    return row


async def find_exercise(s: AsyncSession, class_name: str) -> Optional[Exercise]:
    """마스터에서 종목 조회, 없으면 None"""
    return (await s.exec(select(Exercise).where(Exercise.class_name == class_name))).first()
