from app.core.config import PHASE_CLASSES
from app.phase.enums import CollectStatus, ModelFormat, PhaseModelStatus
from app.phase.models import CollectFileRead
from app.training.utils import bump_version
from app.data.utils import is_supported_class, is_valid_device_id, next_filename

STATUS_PENDING = CollectStatus.PENDING.value
STATUS_LABELING = CollectStatus.LABELING.value
STATUS_LABELED = CollectStatus.LABELED.value
STATUS_FAILED = CollectStatus.FAILED.value
LABEL_STATUSES = tuple(s.value for s in CollectStatus)

VIDEO_EXT = ".mov"
POSE_EXT = ".pose.json"
DATA_EXT = ".parquet"
MODEL_FORMATS = tuple(f.value for f in ModelFormat)
MODEL_STATUS_TRAINING = PhaseModelStatus.TRAINING.value
MODEL_STATUS_COMPLETED = PhaseModelStatus.COMPLETED.value
MODEL_STATUS_FAILED = PhaseModelStatus.FAILED.value


def supports_phase(class_name: str) -> bool:
    """구간 라벨링 지원 종목 판정, PHASE_CLASSES"""
    return class_name in PHASE_CLASSES


def stem(filename: str) -> str:
    """확장자 제거, CSV 영상 pose 공통 이름"""
    return filename[:-4] if filename.endswith(".csv") else filename


def video_name(filename: str) -> str:
    """영상 객체 이름, stem + .mov"""
    return stem(filename) + VIDEO_EXT


def pose_name(filename: str) -> str:
    """pose 객체 이름, stem + .pose.json"""
    return stem(filename) + POSE_EXT


def is_valid_video_start(video_start: float) -> bool:
    """영상 시작 unix 초 검증, 2020년 이후"""
    return video_start > 1_577_836_800


def label_block_reason(entry: CollectFileRead | None) -> str | None:
    """라벨링 불가 사유, 미업로드, 시작시각 없음, 진행 중"""
    if entry is None:
        return "목록에 없는 파일"
    if not entry.uploaded:
        return "업로드 미완료"
    if entry.video_start is None:
        return "영상 시작 시각 없음"
    if entry.is_labeling:
        return "이미 라벨링 중"
    return None


def status_counts(entries: list[CollectFileRead]) -> dict[str, int]:
    """상태별 개수 집계, 대시보드 필터"""
    counts = {s: 0 for s in LABEL_STATUSES}
    for e in entries:
        counts[e.status] = counts.get(e.status, 0) + 1
    counts["total"] = len(entries)
    return counts


def dataset_filename(filename: str) -> str:
    """승격 파일명, stem + .parquet"""
    return stem(filename) + DATA_EXT


def promote_block_reason(entry: CollectFileRead | None) -> str | None:
    """승격 불가 사유, 미업로드, 이미 승격, 라벨 미완료"""
    if entry is None:
        return "목록에 없는 파일"
    if not entry.uploaded:
        return "업로드 미완료"
    if entry.dataset_file is not None:
        return "이미 승격됨"
    return None


def is_valid_model_format(fmt: str) -> bool:
    """다운로드 포맷 검증, pt onnx mlpackage"""
    return fmt in MODEL_FORMATS
