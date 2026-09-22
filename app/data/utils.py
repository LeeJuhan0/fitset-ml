import re

from app.core.config import CLASSES

SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def is_supported_class(class_name: str) -> bool:
    """CLASSES 포함 여부"""
    return class_name in CLASSES


def is_valid_device_id(device_id: str) -> bool:
    """deviceId 형식 검증, 영숫자 64자"""
    return bool(SAFE_ID_RE.match(device_id))


def make_filename(class_name: str, owner_id: str, seq: int) -> str:
    """파일명 규칙, CLASS_owner_NNNN.csv"""
    return f"{class_name}_{owner_id}_{seq:04d}.csv"


def next_filename(entries: list[dict], class_name: str, owner_id: str, *, owner_field: str = "userId") -> str:
    """목록의 기존 항목을 보고 다음 파일명을 정한다 (순수 계산)"""
    existing = {f["filename"] for f in entries}
    seq = sum(
        1 for f in entries
        if f.get("class") == class_name and f.get(owner_field) == owner_id
    ) + 1
    filename = make_filename(class_name, owner_id, seq)
    while filename in existing:
        seq += 1
        filename = make_filename(class_name, owner_id, seq)
    return filename
