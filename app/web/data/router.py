# ─────────────────────────────────────────────────────────────────────────────
# 데이터 도메인 API — 수집 CSV 업로드/조회. main.py가 data_router로 등록.
# 엔드포인트: GET /data, GET /data/presigned-url, POST /data/upload-confirm
# ─────────────────────────────────────────────────────────────────────────────
import re   # deviceId 형식 검증용 정규식

from fastapi import APIRouter, Depends, HTTPException, Query   # APIRouter: 엔드포인트 묶음, Query: 쿼리파라미터, Depends: 의존성주입
from pydantic import BaseModel   # 요청 바디 스키마 정의용

from app.web.deps import validate_platform   # 경로 {platform} 검증(ios/android)
from app.core.config import CLASSES          # 허용 종목 목록
from app.core.s3 import generate_presigned_upload_url, get_index, mark_uploaded, reserve_upload  # S3 헬퍼들

router = APIRouter()   # 이 파일의 엔드포인트들이 등록될 라우터(→ main.py에서 include)

# deviceId는 S3 키에 들어가므로 경로 조작/이상문자 차단
_DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")   # 영숫자·_·-, 1~64자만 허용


@router.get("/api/v1/{platform}/data")
def list_data(platform: str = Depends(validate_platform)):
    # 입력: 경로 {platform}(검증됨). 출력: 인덱스(파일 목록) 전체.
    index = get_index(platform)             # S3 index.json 읽기 → s3.get_index
    return {
        "success": True,
        "code": "200",
        "message": "파일 목록을 조회했습니다.",
        "data": index,                      # {platform, files:[...]} 그대로 반환
    }


@router.get("/api/v1/{platform}/data/presigned-url")
def presigned_url(
    class_name: str = Query(..., alias="class"),     # 쿼리 ?class= (파이썬 예약어라 alias 사용). 종목 라벨
    device_id: str = Query(..., alias="deviceId"),   # 쿼리 ?deviceId= . 기기 식별자
    platform: str = Depends(validate_platform),      # 경로 {platform}
):
    """서버가 인덱스를 보고 파일명을 부여(예약)한 뒤 presigned PUT URL을 발급한다.

    파일명은 클라이언트가 아니라 서버가 ``{CLASS}_{deviceId}_{NNNN}.csv``로 정한다.
    예약(uploaded=False)은 동기 처리되어 동시 요청에도 번호가 겹치지 않는다.
    """
    if class_name not in CLASSES:   # 종목 검증
        raise HTTPException(status_code=400, detail=f"지원하지 않는 종목: {class_name}. 허용: {CLASSES}")
    if not _DEVICE_ID_RE.match(device_id):   # deviceId 형식 검증
        raise HTTPException(status_code=400, detail="유효하지 않은 deviceId")

    # 서버가 인덱스를 보고 파일명을 정해 예약(uploaded=False)
    filename = reserve_upload(platform, class_name, device_id)             # → s3.reserve_upload (파일명 채번)
    url = generate_presigned_upload_url(platform, class_name, filename)    # → s3.generate_presigned_upload_url
    s3_key = f"{platform}/raw/{class_name}/{filename}"                     # 업로드될 최종 S3 키

    return {
        "success": True,
        "code": "200",
        "message": "presigned URL을 발급했습니다.",
        "data": {
            "presignedUrl": url,        # 앱이 이 URL로 CSV를 직접 PUT
            "expiresIn": 300,           # URL 유효시간(초)
            "s3Key": s3_key,            # 업로드 경로
            "filename": filename,       # 서버가 부여한 파일명(앱이 upload-confirm에 다시 보냄)
        },
    }


class UploadConfirmRequest(BaseModel):   # POST 바디 스키마: {filename, class}
    filename: str
    class_name: str   # JSON 키는 아래 Field 없이 그대로 'class_name' (요청 바디 필드명)


@router.post("/api/v1/{platform}/data/upload-confirm")
def upload_confirm(body: UploadConfirmRequest, platform: str = Depends(validate_platform)):
    """S3 PUT 완료 후, presigned 단계에서 예약된 항목을 uploaded=True로 확정한다."""
    # body: 위 스키마로 파싱된 요청 바디. platform: 경로 검증값.
    if body.class_name not in CLASSES:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 종목: {body.class_name}")

    found = mark_uploaded(platform, body.filename)   # → s3.mark_uploaded (예약 항목 uploaded=True). 없으면 False
    if not found:
        raise HTTPException(status_code=404, detail="예약된 파일을 찾을 수 없습니다.")

    return {
        "success": True,
        "code": "200",
        "message": "업로드를 확정했습니다.",
        "data": {"filename": body.filename, "class": body.class_name},
    }
