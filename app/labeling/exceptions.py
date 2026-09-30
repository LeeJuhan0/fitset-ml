from fastapi import HTTPException, status


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


class CollectFileBusyError(HTTPException):
    """라벨링 중이라 삭제 불가"""

    def __init__(self, filename: str):
        """상태코드와 detail 고정"""
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"라벨링 중인 파일은 삭제할 수 없습니다: {filename}",
        )


class ClassChangeBlockedError(HTTPException):
    """승격, 라벨링 중, 미업로드라 종목 변경 불가"""

    def __init__(self, filename: str, reason: str):
        """상태코드와 detail 고정"""
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"종목을 바꿀 수 없습니다({reason}): {filename}",
        )


class PhaseEditBlockedError(HTTPException):
    """승격, 라벨링 중이거나 프레임 수 불일치라 구간 수정 불가"""

    def __init__(self, filename: str, reason: str):
        """상태코드와 detail 고정"""
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"구간을 수정할 수 없습니다({reason}): {filename}",
        )
