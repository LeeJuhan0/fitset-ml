from fastapi import HTTPException, status


class InvalidPlatformError(HTTPException):
    """platform 경로값이 ios, android 가 아님"""

    def __init__(self):
        """상태코드와 detail 고정"""
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="platform must be 'ios' or 'android'",
        )


class AdminAuthLockedError(HTTPException):
    """관리자 자격 미설정, fail closed"""

    def __init__(self):
        """상태코드와 detail 고정"""
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "ADMIN_AUTH_LOCKED", "message": "관리자 자격증명이 설정되지 않았습니다."},
        )


class UnauthorizedError(HTTPException):
    """Basic 인증 실패, 브라우저 재입력 유도 헤더"""

    def __init__(self):
        """상태코드와 detail 고정"""
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "관리자 인증에 실패했습니다."},
            headers={"WWW-Authenticate": 'Basic realm="FitSet Admin"'},
        )
