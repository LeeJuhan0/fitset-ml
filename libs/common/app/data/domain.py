# ─────────────────────────────────────────────────────────────────────────────
# data 도메인 규칙 — I/O 없는 순수 함수/상수만 둔다. (S3·FastAPI import 금지)
# 파일명 채번, deviceId·종목 형식 규칙이 이 도메인의 불변식이다.
# ─────────────────────────────────────────────────────────────────────────────
import re

from app.core.config import CLASSES   # 허용 종목 목록 (설정 상수 — I/O 아님)

# deviceId·userId는 S3 키에 들어가므로 경로 조작/이상문자 차단 — 영숫자·_·-, 1~64자만 허용
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def is_supported_class(class_name: str) -> bool:
    # 종목 라벨 규칙: CLASSES에 등록된 값만 허용
    return class_name in CLASSES


def is_valid_device_id(device_id: str) -> bool:
    return bool(SAFE_ID_RE.match(device_id))


def is_valid_user_id(user_id: str) -> bool:
    # 토큰 sub가 S3 키 prefix로 들어간다 — 백엔드 발급이라도 형식은 방어
    return bool(SAFE_ID_RE.match(user_id))


def make_filename(class_name: str, owner_id: str, seq: int) -> str:
    # 파일명 규칙: {CLASS}_{ownerId}_{NNNN}.csv (순번 4자리) — 유저 수집은 userId가 주인
    return f"{class_name}_{owner_id}_{seq:04d}.csv"


def next_filename(entries: list[dict], class_name: str, owner_id: str, *, owner_field: str = "userId") -> str:
    """대장의 기존 항목을 보고 다음 파일명을 정한다 (순수 계산).

    같은 class+주인(owner) 항목 개수 + 1 = 다음 순번. 이미 존재하는 이름과
    겹치면(삭제로 생긴 구멍 등) 순번을 올려 충돌을 피한다.
    owner_field: 채번 주인을 담는 키 — 유저 업로드 대장은 "userId", 구 인덱스는 "deviceId".
    """
    existing = {f["filename"] for f in entries}
    seq = sum(
        1 for f in entries
        if f.get("class") == class_name and f.get(owner_field) == owner_id
    ) + 1
    filename = make_filename(class_name, owner_id, seq)
    while filename in existing:  # 구멍/중복 방지
        seq += 1
        filename = make_filename(class_name, owner_id, seq)
    return filename
