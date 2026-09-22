from fastapi import HTTPException, status



class UnsupportedClassError(HTTPException):
    """CLASSES 에 없는 종목"""

    def __init__(self, class_name: str):
        """상태코드와 detail 고정"""
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"마스터에 없는 종목: {class_name}",
        )


class InvalidDeviceIdError(HTTPException):
    """S3 키에 못 넣는 deviceId"""

    def __init__(self):
        """상태코드와 detail 고정"""
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="유효하지 않은 deviceId",
        )


class DataFileNotFoundError(HTTPException):
    """목록에 없는 학습 파일"""

    def __init__(self, filename: str):
        """상태코드와 detail 고정"""
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"파일을 찾을 수 없습니다: {filename}",
        )


class ReservationNotFoundError(HTTPException):
    """upload-confirm 대상 예약 없음"""

    def __init__(self):
        """상태코드와 detail 고정"""
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="예약된 파일을 찾을 수 없습니다.",
        )
