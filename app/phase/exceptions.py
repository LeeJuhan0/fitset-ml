from fastapi import HTTPException, status

from app.phase.enums import ModelFormat


class InvalidVideoStartError(HTTPException):
    """videoStart 가 unix 초가 아님"""

    def __init__(self):
        """상태코드와 detail 고정"""
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="videoStart는 영상 첫 프레임의 unix 초여야 합니다",
        )


class EmptyFilenamesError(HTTPException):
    """filenames 비어 있음"""

    def __init__(self):
        """상태코드와 detail 고정"""
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="filenames가 비어 있습니다",
        )


class CollectFileNotFoundError(HTTPException):
    """수집 목록에 없는 파일"""

    def __init__(self, filename: str):
        """상태코드와 detail 고정"""
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"파일을 찾을 수 없습니다: {filename}",
        )


class PoseNotReadyError(HTTPException):
    """라벨링 전이라 pose 없음"""

    def __init__(self, filename: str):
        """상태코드와 detail 고정"""
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"라벨링된 파일이 아닙니다: {filename}",
        )


class UnsupportedPhaseClassError(HTTPException):
    """구간 라벨링 미지원 종목"""

    def __init__(self, class_name: str):
        """상태코드와 detail 고정"""
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"각도 규칙이 없는 종목: {class_name}. exercises 의 angle_joints 와 down_is_decreasing 을 채우면 된다",
        )


class UnknownPhaseFilesError(HTTPException):
    """phase 라벨이 없거나 다른 종목인 학습 파일"""

    def __init__(self, filenames: list[str]):
        """상태코드와 detail 고정"""
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"phase 라벨이 없거나 다른 종목인 파일: {filenames}",
        )


class NoPhaseLabeledFilesError(HTTPException):
    """종목에 학습할 phase 라벨 파일 없음"""

    def __init__(self, class_name: str):
        """상태코드와 detail 고정"""
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{class_name} 의 phase 라벨 파일이 없습니다",
        )


class InvalidModelFormatError(HTTPException):
    """pt onnx mlpackage 외 포맷"""

    def __init__(self):
        """상태코드와 detail 고정"""
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"format 은 {[f.value for f in ModelFormat]} 중 하나",
        )


class ModelArtifactNotFoundError(HTTPException):
    """모델 없음 또는 산출물 미완성"""

    def __init__(self):
        """상태코드와 detail 고정"""
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="모델 또는 산출물이 없습니다",
        )
