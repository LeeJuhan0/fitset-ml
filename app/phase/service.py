import asyncio
import json
import pathlib
import subprocess
import sys
import tempfile

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import s3
from app.core.config import settings
from app.phase import utils
from app.core.schemas import FilenameQuery
from app.data.schemas import PresignedUrlQuery
from app.phase.schemas import (
    LabelData,
    LabelRequest,
    ModelFormatQuery,
    ModelsQuery,
    PhaseTrainRequest,
    PromoteRequest,
    UploadConfirmRequest,
    ListFilesData,
    ListModelsData,
    ModelUrlData,
    PhaseTrainData,
    PoseData,
    PresignedPairData,
    PromoteData,
    UploadConfirmData,
    VideoUrlData,
)
from app.phase.exceptions import (
    CollectFileNotFoundError,
    EmptyFilenamesError,
    InvalidModelFormatError,
    InvalidVideoStartError,
    ModelArtifactNotFoundError,
    NoPhaseLabeledFilesError,
    PoseNotReadyError,
    UnknownPhaseFilesError,
    UnsupportedPhaseClassError,
)
from app.data.exceptions import InvalidDeviceIdError, ReservationNotFoundError, UnsupportedClassError
from app.exercises.repository import folder_for, is_class_known, phase_rule
from app.phase.models import CollectFileRead
from app.phase.repository import (
    CONTENT_TYPES,
    confirm_collect,
    create_phase_model,
    get_file,
    get_phase_model,
    list_files,
    list_phase_models,
    mark_labeling,
    phase_labeled_files,
    phase_model_versions,
    presigned_get_url,
    presigned_put_url,
    promote as promote_row,
    read_pose,
    reserve_collect,
)

PUT_EXPIRES_SECONDS = 600
GET_EXPIRES_SECONDS = 3600


async def issue_upload_urls(s: AsyncSession, platform: str, query: PresignedUrlQuery) -> PresignedPairData:
    """업로드 1단계, 검증 채번 presigned PUT 쌍"""
    class_name, device_id = query.class_name, query.device_id
    if not await is_class_known(s, class_name):
        raise UnsupportedClassError(class_name)
    if not utils.is_valid_device_id(device_id):
        raise InvalidDeviceIdError()
    filename = await reserve_collect(s, platform, class_name, device_id)
    entry = await get_file(s, platform, filename)
    return PresignedPairData.model_validate({
        "filename": filename,
        "csvUrl": presigned_put_url(entry.csv_bucket, entry.csv_key, CONTENT_TYPES["csv"], PUT_EXPIRES_SECONDS),
        "csvKey": entry.csv_key,
        "videoUrl": presigned_put_url(entry.video_bucket, entry.video_key, CONTENT_TYPES["video"], PUT_EXPIRES_SECONDS),
        "videoKey": entry.video_key,
        "expiresIn": PUT_EXPIRES_SECONDS,
    })


async def confirm_upload(s: AsyncSession, platform: str, payload: UploadConfirmRequest) -> UploadConfirmData:
    """업로드 2단계, videoStart 검증, 예약 없으면 404"""
    filename, video_start, rows = payload.filename, payload.video_start, payload.rows
    if not utils.is_valid_video_start(video_start):
        raise InvalidVideoStartError()
    if not await confirm_collect(s, platform, filename, video_start, rows):
        raise ReservationNotFoundError()
    return UploadConfirmData.model_validate({"filename": filename, "status": utils.STATUS_PENDING})


async def files(s: AsyncSession, platform: str) -> ListFilesData:
    """목록 전체 조회, 상태별 개수"""
    entries = await list_files(s, platform)
    return ListFilesData.model_validate({"platform": platform, "files": entries, "counts": utils.status_counts(entries)})


async def start_labeling(s: AsyncSession, platform: str, payload: LabelRequest) -> LabelData:
    """라벨링 가능 파일 선별, labeling 표시, 워커 spawn"""
    filenames = payload.filenames
    if not filenames:
        raise EmptyFilenamesError()
    entries = {f.filename: f for f in await list_files(s, platform)}
    accepted, skipped = [], []
    for name in filenames:
        reason = utils.label_block_reason(entries.get(name))
        if reason is not None:
            skipped.append({"filename": name, "reason": reason})
            continue
        accepted.append(name)
    if not accepted:
        return LabelData.model_validate({"accepted": [], "skipped": skipped})

    await mark_labeling(s, platform, accepted)
    await s.commit()
    spawn_worker(platform, accepted)
    return LabelData.model_validate({"accepted": accepted, "skipped": skipped})


def spawn_worker(platform: str, filenames: list[str]) -> None:
    """phase_labeler 서브프로세스 시작, 로그 임시 파일"""
    log_path = pathlib.Path(tempfile.gettempdir()) / f"phase_labeler_{platform}.log"
    log_file = open(log_path, "a")
    subprocess.Popen(
        [sys.executable, "-m", "app.worker.phase_labeler", "--platform", platform, "--files", json.dumps(filenames)],
        stdout=log_file,
        stderr=log_file,
    )


def _video_location(entry: CollectFileRead) -> tuple[str, str]:
    """영상 위치 선택, 라벨 후 labeled 버킷"""
    if entry.label is not None:
        return entry.label.video_bucket, entry.label.video_key
    return entry.video_bucket, entry.video_key


async def video_url(s: AsyncSession, platform: str, query: FilenameQuery) -> VideoUrlData:
    """영상 재생 presigned GET, 목록에 없으면 404"""
    filename = query.filename
    entry = await get_file(s, platform, filename)
    if entry is None:
        raise CollectFileNotFoundError(filename)
    bucket, key = _video_location(entry)
    return VideoUrlData.model_validate({"filename": filename, "url": presigned_get_url(bucket, key, GET_EXPIRES_SECONDS), "expiresIn": GET_EXPIRES_SECONDS})


async def pose(s: AsyncSession, platform: str, query: FilenameQuery) -> PoseData:
    """관절 phase JSON 조회, 라벨 전 404"""
    filename = query.filename
    entry = await get_file(s, platform, filename)
    if entry is None or entry.label is None:
        raise PoseNotReadyError(filename)
    data = await asyncio.to_thread(read_pose, entry.label.data_bucket, entry.label.pose_key)
    return PoseData.model_validate({"filename": filename, "fps": data["fps"], "frames": data["frames"]})


def _copy_to_dataset(entry: CollectFileRead, key: str) -> str:
    """라벨 parquet 복사, 없으면 CSV → parquet 변환 업로드"""
    if entry.label is not None:
        s3.copy_object(entry.label.data_bucket, entry.label.data_key, settings.raw_data_bucket, key)
        return key
    import pandas as pd

    with tempfile.TemporaryDirectory() as workdir:
        csv_path = pathlib.Path(workdir) / entry.filename
        s3.download_object(entry.csv_bucket, entry.csv_key, str(csv_path))
        df = pd.read_csv(csv_path)
        df.columns = df.columns.str.strip()
        out = csv_path.with_suffix(".parquet")
        df.to_parquet(out, index=False)
        s3.upload_object(settings.raw_data_bucket, key, str(out), CONTENT_TYPES["parquet"])
    return key


async def promote(s: AsyncSession, platform: str, payload: PromoteRequest) -> PromoteData:
    """승격, dataset 버킷 복사, dataset_files 등록, 건너뛴 사유"""
    filenames = payload.filenames
    if not filenames:
        raise EmptyFilenamesError()
    entries = {f.filename: f for f in await list_files(s, platform)}
    promoted, skipped = [], []
    for name in filenames:
        entry = entries.get(name)
        reason = utils.promote_block_reason(entry)
        if reason is not None:
            skipped.append({"filename": name, "reason": reason})
            continue
        key = s3._csv_key(platform, await folder_for(s, entry.class_name), utils.dataset_filename(name))
        await asyncio.to_thread(_copy_to_dataset, entry, key)
        await promote_row(s, 
            platform, name, dataset_filename=utils.dataset_filename(name),
            bucket=settings.raw_data_bucket, key=key, phase_labeled=bool(entry.label and entry.label.has_phase),
        )
        promoted.append(name)
    return PromoteData.model_validate({"promoted": promoted, "skipped": skipped})


async def start_phase_training(s: AsyncSession, platform: str, payload: PhaseTrainRequest) -> PhaseTrainData:
    """종목 검증, 파일 확정, 버전 채번, 워커 spawn"""
    class_name, filenames = payload.class_name, payload.filenames
    epochs, lr, window, stride = payload.epochs, payload.lr, payload.window, payload.stride
    if await phase_rule(s, class_name) is None:
        raise UnsupportedPhaseClassError(class_name)
    candidates = {f.filename for f in await phase_labeled_files(s, platform, class_name)}
    chosen = sorted(candidates) if filenames is None else list(filenames)
    unknown = [f for f in chosen if f not in candidates]
    if unknown:
        raise UnknownPhaseFilesError(unknown)
    if not chosen:
        raise NoPhaseLabeledFilesError(class_name)
    version = utils.bump_version(await phase_model_versions(s, platform, class_name))
    model = await create_phase_model(s, platform, class_name, version, chosen, window=window, stride=stride, epochs=epochs, lr=lr)
    await s.commit()
    spawn_trainer(platform, class_name, model.id, version, chosen, window=window, stride=stride, epochs=epochs, lr=lr)
    return PhaseTrainData.model_validate({"modelId": model.id, "version": version, "class": class_name, "numFiles": len(chosen)})


def spawn_trainer(platform: str, class_name: str, model_id: int, version: str, filenames: list[str], *,
                  window: int, stride: int, epochs: int, lr: float) -> None:
    """phase_trainer 서브프로세스 시작"""
    log_path = pathlib.Path(tempfile.gettempdir()) / f"phase_trainer_{platform}_{class_name}_{version}.log"
    log_file = open(log_path, "w")
    subprocess.Popen(
        [sys.executable, "-m", "app.worker.phase_trainer", "--platform", platform, "--class", class_name,
         "--model-id", str(model_id), "--version", version, "--files", json.dumps(filenames),
         "--window", str(window), "--stride", str(stride), "--epochs", str(epochs), "--lr", str(lr)],
        stdout=log_file,
        stderr=log_file,
    )


async def models(s: AsyncSession, platform: str, query: ModelsQuery) -> ListModelsData:
    """모델 목록"""
    return ListModelsData.model_validate({"platform": platform, "models": await list_phase_models(s, platform, query.class_name)})


async def model_download_url(s: AsyncSession, platform: str, model_id: int, query: ModelFormatQuery) -> ModelUrlData:
    """산출물 presigned GET, 포맷 검증, 미완성이면 404"""
    fmt = query.format
    if not utils.is_valid_model_format(fmt):
        raise InvalidModelFormatError()
    model = await get_phase_model(s, platform, model_id)
    if model is None or not model.can_download:
        raise ModelArtifactNotFoundError()
    key = {"pt": model.pt_key, "onnx": model.onnx_key, "mlpackage": model.mlpackage_key}[fmt]
    if key is None:
        raise ModelArtifactNotFoundError()
    return ModelUrlData.model_validate({"modelId": model_id, "format": fmt, "url": presigned_get_url(model.bucket, key, GET_EXPIRES_SECONDS), "expiresIn": GET_EXPIRES_SECONDS})
