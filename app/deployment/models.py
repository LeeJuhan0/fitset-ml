from pydantic import AwareDatetime
from sqlmodel import Field, Relationship, SQLModel

from app.core.models import CREATED_AT, Platform


class ModelDeployment(SQLModel, table=True):
    """배포 이력, 분류와 종목별 렙카운팅, 최신 행이 현재 배포"""
    __tablename__ = "model_deployments"

    id: int = Field(default=None, primary_key=True)
    kind: str = Field(max_length=16, index=True, description="classifier 또는 phase")
    class_name: str | None = Field(default=None, max_length=64, index=True, description="phase 종목, classifier 는 None")
    version: str = Field(max_length=32)
    bucket: str = Field(max_length=64, description="fitset-models 또는 fitset-phase-models")
    model_key: str = Field(max_length=256, description="플랫폼별 모델 파일 s3 키")
    meta_key: str | None = Field(default=None, max_length=256, description="phase meta.json s3 키, classifier 는 None")

    platform_id: int = Field(foreign_key="platforms.id", index=True)
    platform: Platform = Relationship(sa_relationship_kwargs={"lazy": "joined"})

    created_at: AwareDatetime = Field(**CREATED_AT)

    def __str__(self):
        """표시 문자열"""
        return f"{self.platform}/{self.kind}/{self.class_name or '-'}/{self.version}"
