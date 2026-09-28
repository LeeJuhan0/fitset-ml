from enum import Enum


class CollectStatus(str, Enum):
    """수집 파일 상태, pending → labeling → labeled | failed"""
    PENDING = "pending"
    LABELING = "labeling"
    LABELED = "labeled"
    FAILED = "failed"
