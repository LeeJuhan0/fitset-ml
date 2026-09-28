
from pydantic import model_validator

from sqlmodel import Field

from app.phase.models import PhaseModelRead
from app.core.schemas import CamelModel


class PhaseTrainRequest(CamelModel):
    """train 바디, class, filenames 선택, 하이퍼파라미터"""
    class_name: str = Field(alias="class")
    filenames: list[str] | None = None
    epochs: int = Field(default=20, ge=1, le=500)
    lr: float = Field(default=1e-3, gt=0)
    window: int = Field(default=50, ge=10, le=500)
    stride: int = Field(default=5, ge=1, le=100)

    @model_validator(mode="before")
    @classmethod
    def dedup_filenames(cls, data: dict):
        """중복·빈 이름 제거, 순서 유지"""
        names = data.get("filenames")
        if isinstance(names, list):
            data["filenames"] = list(dict.fromkeys(n for n in names if n))
        return data


class PhaseTrainResponse(CamelModel):
    """train 응답, modelId, version, class, numFiles"""
    model_id: int
    version: str
    class_name: str = Field(alias="class")
    num_files: int


class ListModelsResponse(CamelModel):
    """models 응답, 종목별 렙카운팅 모델 목록"""
    platform: str
    models: list[PhaseModelRead]


class ModelUrlResponse(CamelModel):
    """download-url 응답, presigned GET"""
    model_id: int
    format: str
    url: str
    expires_in: int


class ModelsRequest(CamelModel):
    """?class= 쿼리, 없으면 전체 종목"""
    class_name: str | None = None


class ModelFormatRequest(CamelModel):
    """?format= 쿼리, pt onnx mlpackage"""
    format: str
