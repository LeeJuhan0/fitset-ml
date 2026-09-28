from app.phase.enums import ModelFormat, PhaseModelStatus
from app.training.utils import bump_version

MODEL_FORMATS = tuple(f.value for f in ModelFormat)
MODEL_STATUS_TRAINING = PhaseModelStatus.TRAINING.value
MODEL_STATUS_COMPLETED = PhaseModelStatus.COMPLETED.value
MODEL_STATUS_FAILED = PhaseModelStatus.FAILED.value


def is_valid_model_format(fmt: str) -> bool:
    """다운로드 포맷 검증, pt onnx mlpackage"""
    return fmt in MODEL_FORMATS
