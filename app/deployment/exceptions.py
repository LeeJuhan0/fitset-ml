from fastapi import HTTPException, status


class NoTrainingHistoryError(HTTPException):
    """experiment 없음"""

    def __init__(self):
        """상태코드와 detail 고정"""
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="학습 이력이 없습니다.",
        )


class VersionNotFoundError(HTTPException):
    """해당 버전 run 없음"""

    def __init__(self, version: str):
        """상태코드와 detail 고정"""
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"버전 {version}의 학습 결과가 없습니다.",
        )


class NoDeployedModelError(HTTPException):
    """latest.json 없음"""

    def __init__(self):
        """상태코드와 detail 고정"""
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="배포된 모델이 없습니다.",
        )
