# ─────────────────────────────────────────────────────────────────────────────
# data 도메인 API(controller) — 형식 검증·응답 포장만 하고 유스케이스는 service에 위임.
# 엔드포인트: GET /data, GET /data/stats, GET /data/presigned-url, POST /data/upload-confirm
# ─────────────────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_trace_id, validate_platform   # traceId 주입, 경로 {platform} 검증(ios/android)
from app.core.config import CLASSES                    # 에러 메시지용 허용 목록
from app.core.schemas import ApiResponse
from app.data import domain, service
from app.data.schemas import (
    FileStatsData,
    ListDataData,
    PresignedUrlData,
    UploadConfirmData,
    UploadConfirmRequest,
)

router = APIRouter()


@router.get("/api/v1/{platform}/data", response_model=ApiResponse[ListDataData])
def list_data(
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    return {"trace_id": trace_id, "data": service.list_data(platform)}


@router.get("/api/v1/{platform}/data/stats", response_model=ApiResponse[FileStatsData])
def data_stats(
    filename: str = Query(...),   # 쿼리 ?filename= . 인덱스에 등록된 CSV 파일명
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    stats = service.file_stats(platform, filename)
    if stats is None:
        raise HTTPException(status_code=404, detail=f"파일을 찾을 수 없습니다: {filename}")

    return {"trace_id": trace_id, "data": stats}


@router.get("/api/v1/{platform}/data/presigned-url", response_model=ApiResponse[PresignedUrlData])
def presigned_url(
    class_name: str = Query(..., alias="class"),     # 쿼리 ?class= (파이썬 예약어라 alias 사용). 종목 라벨
    device_id: str = Query(..., alias="deviceId"),   # 쿼리 ?deviceId= . 기기 식별자
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    # 형식 검증(controller 몫) — 규칙 판정 자체는 domain의 순수 함수
    if not domain.is_supported_class(class_name):
        raise HTTPException(status_code=400, detail=f"지원하지 않는 종목: {class_name}. 허용: {CLASSES}")
    if not domain.is_valid_device_id(device_id):
        raise HTTPException(status_code=400, detail="유효하지 않은 deviceId")

    return {"trace_id": trace_id, "data": service.issue_upload_url(platform, class_name, device_id)}


@router.post("/api/v1/{platform}/data/upload-confirm", response_model=ApiResponse[UploadConfirmData])
def upload_confirm(
    body: UploadConfirmRequest,
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    if not domain.is_supported_class(body.class_name):
        raise HTTPException(status_code=400, detail=f"지원하지 않는 종목: {body.class_name}")

    if not service.confirm_upload(platform, body.filename):
        raise HTTPException(status_code=404, detail="예약된 파일을 찾을 수 없습니다.")

    return {"trace_id": trace_id, "data": {"filename": body.filename, "class": body.class_name}}
