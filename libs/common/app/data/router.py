# ─────────────────────────────────────────────────────────────────────────────
# data 도메인 API(controller) — 형식 검증·응답 포장만 하고 유스케이스는 service에 위임.
# 라우터 2개로 분리 — 호출 주체가 다르면 인증도 다르다:
#   router(유저, /api/v1):        GET /data/presigned-url, POST /data/upload-confirm — 앱이 직접 호출
#   admin_router(어드민 호스트 /api/v1): GET /data, GET /data/stats — 대시보드/운영 조회
# ─────────────────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import check_basic_auth         # 어드민 Basic 인증
from app.deps import get_current_user_id, get_trace_id, validate_platform   # 유저 JWT 검증, traceId 주입, {platform} 검증
from app.core.config import CLASSES                    # 에러 메시지용 허용 목록
from app.core.schemas import ApiResponse
from app.data import domain, service
from app.data.schemas import (
    FileStatsData,
    ListDataData,
    ListUploadsData,
    PresignedUrlData,
    UploadConfirmData,
    UploadConfirmRequest,
    UploadDecisionData,
)

# prefix는 각 서비스 main이 등록한다 — 유저 /ml/v1, 어드민 /api/v1 (호스트가 경계)
router = APIRouter(                             # 유저용 — 앱이 직접 호출, 전 엔드포인트에 JWT 검증
    dependencies=[Depends(get_current_user_id)],
)
admin_router = APIRouter(                       # 어드민용 — 전 엔드포인트에 Basic 인증
    dependencies=[Depends(check_basic_auth)],
)


@admin_router.get("/{platform}/data", response_model=ApiResponse[ListDataData])
def list_data(
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    return {"trace_id": trace_id, "data": service.list_data(platform)}


@admin_router.get("/{platform}/data/stats", response_model=ApiResponse[FileStatsData])
def data_stats(
    filename: str = Query(...),   # 쿼리 ?filename= . 인덱스에 등록된 CSV 파일명
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    stats = service.file_stats(platform, filename)
    if stats is None:
        raise HTTPException(status_code=404, detail=f"파일을 찾을 수 없습니다: {filename}")

    return {"trace_id": trace_id, "data": stats}


@router.get("/{platform}/data/presigned-url", response_model=ApiResponse[PresignedUrlData])
def presigned_url(
    class_name: str = Query(..., alias="class"),     # 쿼리 ?class= (파이썬 예약어라 alias 사용). 종목 라벨
    device_id: str = Query(..., alias="deviceId"),   # 쿼리 ?deviceId= . 기기 식별자(한 유저의 복수 기기 구분 메타)
    platform: str = Depends(validate_platform),
    user_id: str = Depends(get_current_user_id),     # 토큰 sub — 라우터 의존성 캐시라 재검증 비용 없음
    trace_id: str = Depends(get_trace_id),
):
    # 형식 검증(controller 몫) — 규칙 판정 자체는 domain의 순수 함수
    if not domain.is_supported_class(class_name):
        raise HTTPException(status_code=400, detail=f"지원하지 않는 종목: {class_name}. 허용: {CLASSES}")
    if not domain.is_valid_device_id(device_id):
        raise HTTPException(status_code=400, detail="유효하지 않은 deviceId")
    if not domain.is_valid_user_id(user_id):
        # 백엔드 발급 토큰이라도 sub가 S3 키 prefix로 들어가므로 형식은 방어한다
        raise HTTPException(status_code=400, detail="유효하지 않은 userId")

    return {"trace_id": trace_id, "data": service.issue_upload_url(platform, class_name, user_id, device_id)}


@router.post("/{platform}/data/upload-confirm", response_model=ApiResponse[UploadConfirmData])
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


# ── 어드민 직행 업로드 — 검증된 데이터를 dataset 버킷에 바로 (승격 불필요, 학습 인덱스 직등록) ──

@admin_router.get("/{platform}/data/presigned-url", response_model=ApiResponse[PresignedUrlData])
def admin_presigned_url(
    class_name: str = Query(..., alias="class"),     # 쿼리 ?class= . 종목 라벨
    device_id: str = Query(..., alias="deviceId"),   # 쿼리 ?deviceId= . 수집 기기 식별자(채번 주인)
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    if not domain.is_supported_class(class_name):
        raise HTTPException(status_code=400, detail=f"지원하지 않는 종목: {class_name}. 허용: {CLASSES}")
    if not domain.is_valid_device_id(device_id):
        raise HTTPException(status_code=400, detail="유효하지 않은 deviceId")

    return {"trace_id": trace_id, "data": service.admin_issue_upload_url(platform, class_name, device_id)}


@admin_router.post("/{platform}/data/upload-confirm", response_model=ApiResponse[UploadConfirmData])
def admin_upload_confirm(
    body: UploadConfirmRequest,
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    if not domain.is_supported_class(body.class_name):
        raise HTTPException(status_code=400, detail=f"지원하지 않는 종목: {body.class_name}")

    if not service.admin_confirm_upload(platform, body.filename):
        raise HTTPException(status_code=404, detail="예약된 파일을 찾을 수 없습니다.")

    return {"trace_id": trace_id, "data": {"filename": body.filename, "class": body.class_name}}


# ── 유저 업로드 대장·승격 (어드민) — 승격 수행 로직은 service 스텁, 라우터는 501로 응답 ──

@admin_router.get("/{platform}/uploads", response_model=ApiResponse[ListUploadsData])
def list_uploads(
    status: str | None = Query(None),   # 쿼리 ?status= (pending/approved/rejected). 없으면 전체
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    if status is not None and status not in service.UPLOAD_STATUSES:
        raise HTTPException(status_code=400, detail=f"유효하지 않은 status: {status}. 허용: {sorted(service.UPLOAD_STATUSES)}")

    return {"trace_id": trace_id, "data": service.list_uploads(platform, status)}


def _not_implemented() -> HTTPException:
    # 승격 인터페이스는 확정, 처리 로직은 구현 예정 — 계약을 501로 명시(500 내부오류와 구분)
    return HTTPException(status_code=501, detail={"code": "NOT_IMPLEMENTED", "message": "승격 처리는 구현 예정입니다."})


@admin_router.post("/{platform}/uploads/{filename}/approve", response_model=ApiResponse[UploadDecisionData])
def approve_upload(
    filename: str,
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    try:
        return {"trace_id": trace_id, "data": service.promote_upload(platform, filename)}
    except NotImplementedError:
        raise _not_implemented()


@admin_router.post("/{platform}/uploads/{filename}/reject", response_model=ApiResponse[UploadDecisionData])
def reject_upload(
    filename: str,
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    try:
        return {"trace_id": trace_id, "data": service.reject_upload(platform, filename)}
    except NotImplementedError:
        raise _not_implemented()
