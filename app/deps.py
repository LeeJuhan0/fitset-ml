# ─────────────────────────────────────────────────────────────────────────────
# 공통 의존성(Dependency). FastAPI의 Depends(...)로 여러 도메인 라우터에 횡단 주입된다.
# 모든 라우터의 함수 시그니처에 `platform: str = Depends(validate_platform)`로 들어가,
# 경로의 {platform} 값을 핸들러 본문 실행 "전에" 검증한다.
# ─────────────────────────────────────────────────────────────────────────────
from fastapi import Path, HTTPException   # Path: 경로 파라미터 선언, HTTPException: 즉시 에러 응답
from app.core.config import PLATFORMS     # 허용 플랫폼 집합 {"ios", "android"}


def validate_platform(platform: str = Path(...)) -> str:
    # platform: 경로 변수 {platform}에서 받음. Path(...)의 ...는 "필수"라는 뜻.
    if platform not in PLATFORMS:                       # ios/android 외 값이면
        raise HTTPException(status_code=400, detail="platform must be 'ios' or 'android'")  # 400 거절
    return platform                                     # 통과 시 검증된 값을 핸들러로 전달
