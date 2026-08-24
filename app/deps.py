# ─────────────────────────────────────────────────────────────────────────────
# 공통 의존성(Dependency). FastAPI의 Depends(...)로 여러 도메인 라우터에 횡단 주입된다.
# 모든 라우터의 함수 시그니처에 `platform: str = Depends(validate_platform)`로 들어가,
# 경로의 {platform} 값을 핸들러 본문 실행 "전에" 검증한다.
# ─────────────────────────────────────────────────────────────────────────────
from fastapi import Path, HTTPException, Request   # Path: 경로 파라미터 선언, HTTPException: 즉시 에러 응답
from app.core import auth                          # 유저 JWT 검증(JWKS RS256)
from app.core.config import PLATFORMS              # 허용 플랫폼 집합 {"ios", "android"}


def get_trace_id(request: Request) -> str:
    # trace_id_middleware(main.py)가 request.state에 넣은 traceId를 꺼낸다.
    # 라우터에서 Depends(get_trace_id)로 받아 성공 응답 {trace_id, data}에 넣는다.
    return request.state.trace_id


def get_current_user_id(request: Request) -> str:
    # Authorization Bearer JWT를 검증하고 userId(sub)를 돌려준다 — 유저용 엔드포인트 전용.
    # 검증 실패는 HTTPException(401) → main.py 핸들러가 {traceId, error} 규약으로 번역.
    # 라우터 dependencies와 파라미터에 중복 선언돼도 FastAPI가 요청당 1회만 실행해 캐시한다.
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization 헤더가 없습니다.")
    return auth.verify_token(header.removeprefix("Bearer ").strip())


def validate_platform(platform: str = Path(...)) -> str:
    # platform: 경로 변수 {platform}에서 받음. Path(...)의 ...는 "필수"라는 뜻.
    if platform not in PLATFORMS:                       # ios/android 외 값이면
        raise HTTPException(status_code=400, detail="platform must be 'ios' or 'android'")  # 400 거절
    return platform                                     # 통과 시 검증된 값을 핸들러로 전달
