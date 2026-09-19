# ─────────────────────────────────────────────────────────────────────────────
# data 도메인 Repository — 어드민 직행 업로드 예약/확정, presigned URL, 업로드 대장 조회,
# 학습 인덱스(신뢰 영역) 조회. core.s3(인프라 엔진) 위에서 이 도메인의 저장소 접근만 구현한다.
# ─────────────────────────────────────────────────────────────────────────────
import threading   # 인프로세스 예약 직렬화 락
from datetime import datetime, timezone

from app.core import s3
from app.core.s3 import get_index, get_uploads_index   # noqa: F401 — 도메인 저장소 표면으로 재노출 (service가 사용)
from app.data import domain

# 예약을 직렬화하는 인프로세스 락 — "동기 처리"로 동시 요청에 같은 번호가 안 나가게.
# (update_index의 ETag 조건부 쓰기가 교차 프로세스까지 보장하고, 이 락은 인프로세스 직렬화)
_reserve_lock = threading.Lock()


def download_csv_bytes(platform: str, class_name: str, filename: str) -> bytes:
    # 통계 조회용 — CSV 객체 본문을 통째로 읽어 반환(임시파일 없이 메모리로).
    obj = s3._client().get_object(
        Bucket=s3.settings.raw_data_bucket,
        Key=s3._csv_key(platform, class_name, filename),
    )
    return obj["Body"].read()


def csv_key(platform: str, class_name: str, filename: str) -> str:
    # 업로드될 최종 S3 키 — 키 조립 규칙은 core가 정본
    return s3._csv_key(platform, class_name, filename)


# ── 어드민 직행 업로드 — 검증된 데이터를 dataset 버킷(신뢰 영역)에 바로 올린다 ──

def reserve_admin_upload(platform: str, class_name: str, device_id: str) -> str:
    """학습 인덱스(index.json)에 예약(uploaded=False)하고 파일명을 반환한다.

    어드민이 올리는 데이터는 이미 검증된 것으로 간주 — 승격 단계 없이 confirm만 되면
    학습 대상이다. 채번 주인은 수집 기기(deviceId, 구 수집앱 규칙 유지).
    """
    assigned: dict = {}

    def _reserve(index: dict):
        filename = domain.next_filename(
            index["files"], class_name, device_id, owner_field="deviceId"
        )
        index["files"].append({
            "filename": filename,
            "class": class_name,
            "deviceId": device_id,
            "collectedAt": datetime.now(timezone.utc).isoformat(),
            "uploaded": False,
            "trainedInVersion": None,
        })
        assigned["filename"] = filename

    with _reserve_lock:               # 인프로세스 직렬화
        s3.update_index(platform, _reserve)
    return assigned["filename"]


def mark_admin_uploaded(platform: str, filename: str) -> bool:
    """학습 인덱스의 예약 항목을 업로드 완료(uploaded=True)로 표시한다. 없으면 False(멱등)."""
    result = {"found": False}

    def _mark(index: dict):
        result["found"] = False  # 재시도마다 리셋
        for f in index["files"]:
            if f["filename"] == filename:
                f["uploaded"] = True
                result["found"] = True
                return

    s3.update_index(platform, _mark)
    return result["found"]


def generate_presigned_admin_upload_url(platform: str, class_name: str, filename: str, expires: int = 300) -> str:
    # 어드민이 직접 PUT할 임시 서명 URL — 신뢰 버킷(dataset)의 raw 경로로 발급
    return s3._client().generate_presigned_url(
        "put_object",
        Params={
            "Bucket": s3.settings.raw_data_bucket,
            "Key": s3._csv_key(platform, class_name, filename),
            "ContentType": "text/csv",
        },
        ExpiresIn=expires,
    )
