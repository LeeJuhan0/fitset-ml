# ─────────────────────────────────────────────────────────────────────────────
# data 도메인 Repository — 유저 업로드 대장(uploads 버킷) 예약/확정, presigned URL,
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


def reserve_user_upload(platform: str, class_name: str, user_id: str, device_id: str) -> str:
    """업로드 대장을 보고 다음 파일명을 정해 예약(uploaded=False, pending)하고 반환한다.

    파일명 채번 주인은 userId(토큰 sub). deviceId는 한 유저의 복수 기기 구분용 메타.
    파일명 규칙은 domain.next_filename(순수 계산)이 정하고, 여기는 원자적
    read-modify-write(core.s3.update_uploads_index)로 저장만 책임진다.
    """
    assigned: dict = {}   # 콜백이 정한 파일명을 밖으로 빼내는 통로

    def _reserve(index: dict):
        filename = domain.next_filename(index["uploads"], class_name, user_id)
        index["uploads"].append({             # 예약 항목 추가(아직 업로드 전, 미검증 격리 영역)
            "filename": filename,
            "class": class_name,
            "userId": user_id,
            "deviceId": device_id,
            "collectedAt": datetime.now(timezone.utc).isoformat(),
            "uploaded": False,
            "status": "pending",              # pending → (어드민 승인) approved | rejected
        })
        assigned["filename"] = filename

    with _reserve_lock:               # 인프로세스 직렬화
        s3.update_uploads_index(platform, _reserve)
    return assigned["filename"]


def mark_user_uploaded(platform: str, filename: str) -> bool:
    """업로드 대장의 예약 항목을 업로드 완료(uploaded=True)로 표시한다.

    해당 filename 항목을 찾아 표시하면 True, 없으면 False를 반환한다(멱등).
    """
    result = {"found": False}

    def _mark(index: dict):
        result["found"] = False  # 재시도마다 리셋
        for f in index["uploads"]:
            if f["filename"] == filename:
                f["uploaded"] = True
                result["found"] = True
                return

    s3.update_uploads_index(platform, _mark)
    return result["found"]


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


def upload_csv_key(platform: str, user_id: str, filename: str) -> str:
    # 유저 업로드가 착지할 S3 키 — 키 조립 규칙은 core가 정본
    return s3._upload_csv_key(platform, user_id, filename)


def generate_presigned_user_upload_url(platform: str, user_id: str, filename: str, expires: int = 300) -> str:
    # 앱이 직접 PUT할 수 있는 임시 서명 URL — 격리 버킷(user_uploads)에만 발급한다.
    return s3._client().generate_presigned_url(
        "put_object",           # 허용 동작: 업로드(PUT)
        Params={
            "Bucket": s3.settings.user_uploads_bucket,
            "Key": s3._upload_csv_key(platform, user_id, filename),   # 업로드될 키
            "ContentType": "text/csv",                                # 업로드 시 이 Content-Type이어야 함
        },
        ExpiresIn=expires,      # 유효시간(초, 기본 300)
    )
