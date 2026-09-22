from fastapi import HTTPException, status


class TrainingAlreadyRunningError(HTTPException):
    """같은 플랫폼 학습 진행 중"""

    def __init__(self):
        """상태코드와 detail 고정"""
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail="해당 플랫폼 학습이 이미 진행 중입니다.",
        )


class UntrainableFilesError(HTTPException):
    """미등록 또는 업로드 미완료 파일"""

    def __init__(self, filenames: list[str]):
        """상태코드와 detail 고정"""
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"학습할 수 없는 파일(미등록 또는 업로드 미완료): {filenames}",
        )


class JobNotFoundError(HTTPException):
    """MLflow 에 없는 jobId"""

    def __init__(self):
        """상태코드와 detail 고정"""
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 jobId의 작업이 없습니다.",
        )
