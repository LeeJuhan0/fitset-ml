import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import validate_platform
from app.core.config import CLASSES
from app.core.s3 import generate_presigned_upload_url, get_index, mark_uploaded, reserve_upload

router = APIRouter()

# deviceId는 S3 키에 들어가므로 경로 조작/이상문자 차단
_DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@router.get("/api/v1/{platform}/data")
def list_data(platform: str = Depends(validate_platform)):
    index = get_index(platform)
    return {
        "success": True,
        "code": "200",
        "message": "파일 목록을 조회했습니다.",
        "data": index,
    }


@router.get("/api/v1/{platform}/data/presigned-url")
def presigned_url(
    class_name: str = Query(..., alias="class"),
    device_id: str = Query(..., alias="deviceId"),
    platform: str = Depends(validate_platform),
):
    """서버가 인덱스를 보고 파일명을 부여(예약)한 뒤 presigned PUT URL을 발급한다.

    파일명은 클라이언트가 아니라 서버가 ``{CLASS}_{deviceId}_{NNNN}.csv``로 정한다.
    예약(uploaded=False)은 동기 처리되어 동시 요청에도 번호가 겹치지 않는다.
    """
    if class_name not in CLASSES:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 종목: {class_name}. 허용: {CLASSES}")
    if not _DEVICE_ID_RE.match(device_id):
        raise HTTPException(status_code=400, detail="유효하지 않은 deviceId")

    try:
        url = generate_presigned_upload_url(platform, class_name, filename)
    except Exception:
        # 예약만 되고 URL 발급 실패 → 예약 취소(항목 제거)는 구현 비용이 높으므로,
        # 최소한 클라이언트에게 명확한 5xx를 전달하고 모니터링에서 고아 항목을 주기적으로 정리.
        raise
    s3_key = f"{platform}/raw/{class_name}/{filename}"

    return {
        "success": True,
        "code": "200",
        "message": "presigned URL을 발급했습니다.",
        "data": {
            "presignedUrl": url,
            "expiresIn": 300,
            "s3Key": s3_key,
            "filename": filename,
        },
    }


class UploadConfirmRequest(BaseModel):
    filename: str
    class_name: str


@router.post("/api/v1/{platform}/data/upload-confirm")
def upload_confirm(body: UploadConfirmRequest, platform: str = Depends(validate_platform)):
    """S3 PUT 완료 후, presigned 단계에서 예약된 항목을 uploaded=True로 확정한다."""
    if body.class_name not in CLASSES:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 종목: {body.class_name}")

    found = mark_uploaded(platform, body.filename)
    if not found:
        raise HTTPException(status_code=404, detail="예약된 파일을 찾을 수 없습니다.")

    return {
        "success": True,
        "code": "200",
        "message": "업로드를 확정했습니다.",
        "data": {"filename": body.filename, "class": body.class_name},
    }
