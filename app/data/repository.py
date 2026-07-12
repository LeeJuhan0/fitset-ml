# ─────────────────────────────────────────────────────────────────────────────
# data 도메인 Repository — index.json 항목 예약/확정, 업로드 presigned URL.
# core.s3(인프라 엔진) 위에서 이 도메인의 저장소 접근만 구현한다.
# ─────────────────────────────────────────────────────────────────────────────
import threading   # 인프로세스 예약 직렬화 락
from datetime import datetime, timezone

from app.core import s3
from app.core.s3 import get_index   # noqa: F401 — 도메인 저장소 표면으로 재노출 (service가 사용)
from app.data import domain

# 예약을 직렬화하는 인프로세스 락 — "동기 처리"로 동시 요청에 같은 번호가 안 나가게.
# (update_index의 ETag 조건부 쓰기가 교차 프로세스까지 보장하고, 이 락은 인프로세스 직렬화)
_reserve_lock = threading.Lock()


def reserve_upload(platform: str, class_name: str, device_id: str) -> str:
    """인덱스를 보고 다음 파일명을 정해 예약(uploaded=False)하고 그 파일명을 반환한다.

    파일명 규칙은 domain.next_filename(순수 계산)이 정하고, 여기는 원자적
    read-modify-write(core.s3.update_index)로 저장만 책임진다.
    """
    assigned: dict = {}   # 콜백이 정한 파일명을 밖으로 빼내는 통로

    def _reserve(index: dict):
        filename = domain.next_filename(index["files"], class_name, device_id)
        index["files"].append({               # 예약 항목 추가(아직 업로드 전)
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


def mark_uploaded(platform: str, filename: str) -> bool:
    """예약된 항목을 업로드 완료(uploaded=True)로 표시한다.

    해당 filename 항목을 찾아 표시하면 True, 없으면 False를 반환한다(멱등).
    """
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


def csv_key(platform: str, class_name: str, filename: str) -> str:
    # 업로드될 최종 S3 키 — 키 조립 규칙은 core가 정본
    return s3._csv_key(platform, class_name, filename)


def generate_presigned_upload_url(platform: str, class_name: str, filename: str, expires: int = 300) -> str:
    # 클라이언트가 직접 PUT할 수 있는 임시 서명 URL 생성.
    return s3._client().generate_presigned_url(
        "put_object",           # 허용 동작: 업로드(PUT)
        Params={
            "Bucket": s3.settings.raw_data_bucket,
            "Key": s3._csv_key(platform, class_name, filename),   # 업로드될 키
            "ContentType": "text/csv",                            # 업로드 시 이 Content-Type이어야 함
        },
        ExpiresIn=expires,      # 유효시간(초, 기본 300)
    )
