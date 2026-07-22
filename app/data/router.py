# ─────────────────────────────────────────────────────────────────────────────
# data 도메인 API(controller) — 형식 검증·응답 포장만 하고 유스케이스는 service에 위임.
# 엔드포인트: GET /data, GET /data/presigned-url, POST /data/upload-confirm
# ─────────────────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import validate_platform      # 경로 {platform} 검증(ios/android)
from app.core.config import CLASSES         # 에러 메시지용 허용 목록
from app.core.schemas import Envelope
from app.data import domain, service
from app.data.schemas import ListDataData, PresignedUrlData, UploadConfirmData, UploadConfirmRequest

router = APIRouter()


@router.get("/api/v1/{platform}/data", response_model=Envelope[ListDataData])
def list_data(platform: str = Depends(validate_platform)):
    return {
        "success": True,
        "code": "200",
        "message": "파일 목록을 조회했습니다.",
        "data": service.list_data(platform),
    }


@router.get("/api/v1/{platform}/data/presigned-url", response_model=Envelope[PresignedUrlData])
def presigned_url(
    class_name: str = Query(..., alias="class"),     # 쿼리 ?class= (파이썬 예약어라 alias 사용). 종목 라벨
    device_id: str = Query(..., alias="deviceId"),   # 쿼리 ?deviceId= . 기기 식별자
    platform: str = Depends(validate_platform),
):
    # 형식 검증(controller 몫) — 규칙 판정 자체는 domain의 순수 함수
    if not domain.is_supported_class(class_name):
        raise HTTPException(status_code=400, detail=f"지원하지 않는 종목: {class_name}. 허용: {CLASSES}")
    if not domain.is_valid_device_id(device_id):
        raise HTTPException(status_code=400, detail="유효하지 않은 deviceId")

    return {
        "success": True,
        "code": "200",
        "message": "presigned URL을 발급했습니다.",
        "data": service.issue_upload_url(platform, class_name, device_id),
    }


@router.post("/api/v1/{platform}/data/upload-confirm", response_model=Envelope[UploadConfirmData])
def upload_confirm(body: UploadConfirmRequest, platform: str = Depends(validate_platform)):
    if not domain.is_supported_class(body.class_name):
        raise HTTPException(status_code=400, detail=f"지원하지 않는 종목: {body.class_name}")

    if not service.confirm_upload(platform, body.filename):
        raise HTTPException(status_code=404, detail="예약된 파일을 찾을 수 없습니다.")

    return {
        "success": True,
        "code": "200",
        "message": "업로드를 확정했습니다.",
        "data": {"filename": body.filename, "class": body.class_name},
    }
