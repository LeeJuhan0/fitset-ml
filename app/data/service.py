# ─────────────────────────────────────────────────────────────────────────────
# data 도메인 Service — 유스케이스 조율. repository(저장소)와 domain(규칙)을 조립한다.
# HTTP를 모른다(형식 검증·상태코드는 router 담당).
# ─────────────────────────────────────────────────────────────────────────────
from app.data.repository import (   # 이름으로 import — 테스트가 이 네임스페이스를 monkeypatch 한다
    csv_key,
    generate_presigned_upload_url,
    get_index,
    mark_uploaded,
    reserve_upload,
)

PRESIGNED_EXPIRES_SECONDS = 300   # 업로드 URL 유효시간


def list_data(platform: str) -> dict:
    # 등록된 파일 목록 전체 — {platform, files:[...]} 그대로 반환
    return get_index(platform)


def issue_upload_url(platform: str, class_name: str, device_id: str) -> dict:
    """파일명 채번·예약 → presigned PUT URL 발급까지의 업로드 1단계 유스케이스."""
    filename = reserve_upload(platform, class_name, device_id)             # 예약(uploaded=False)
    url = generate_presigned_upload_url(platform, class_name, filename)    # 서명 URL
    return {
        "presignedUrl": url,                              # 앱이 이 URL로 CSV를 직접 PUT
        "expiresIn": PRESIGNED_EXPIRES_SECONDS,           # URL 유효시간(초)
        "s3Key": csv_key(platform, class_name, filename), # 업로드 경로
        "filename": filename,                             # 서버가 부여한 파일명(앱이 upload-confirm에 다시 보냄)
    }


def confirm_upload(platform: str, filename: str) -> bool:
    """S3 PUT 완료 후 예약 항목을 uploaded=True로 확정. 예약이 없으면 False."""
    return mark_uploaded(platform, filename)
