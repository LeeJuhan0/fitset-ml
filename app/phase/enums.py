from enum import Enum


class PhaseModelStatus(str, Enum):
    """렙카운팅 모델 상태, training → completed | failed"""
    TRAINING = "training"
    COMPLETED = "completed"
    FAILED = "failed"


class ModelFormat(str, Enum):
    """다운로드 가능한 산출물 포맷"""
    PT = "pt"
    ONNX = "onnx"
    MLPACKAGE = "mlpackage"
