import asyncio
import json
import pathlib
import subprocess
import sys
import tempfile

from botocore.exceptions import BotoCoreError, ClientError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.labeling.schemas import (
    DeleteFileResponse,
    LabelResponse,
    ListFilesResponse,
    PoseResponse,
    PresignedPairResponse,
    PromoteResponse,
    SkippedFile,
    UploadConfirmResponse,
    VideoUrlResponse,
)
from app.core import s3
from app.core.config import settings
from app.labeling import algo, utils
from app.labeling.exceptions import (
    ClassChangeBlockedError,
    CollectFileBusyError,
    CollectFileNotFoundError,
    EmptyFilenamesError,
    InvalidVideoStartError,
    PhaseEditBlockedError,
    PoseNotReadyError,
)
from app.data.exceptions import InvalidDeviceIdError, ReservationNotFoundError, UnsupportedClassError
from app.exercises.repository import folder_for, is_class_known
from app.labeling.models import CollectFileRead
from app.labeling.repository import (
    CONTENT_TYPES,
    confirm_collect,
    change_collect_class,
    delete_collect,
    get_file,
    list_files,
    mark_labeling,
    presigned_get_url,
    presigned_put_url,
    complete_promotion,
    read_pose,
    reserve_collect,
    reserve_promotion,
    update_phase_summary,
)

PUT_EXPIRES_SECONDS = 600
GET_EXPIRES_SECONDS = 3600


async def issue_upload_urls(s: AsyncSession, platform: str, class_name: str, device_id: str) -> PresignedPairResponse:
    """업로드 1단계, 검증 채번 presigned PUT 쌍"""
    if not await is_class_known(s, class_name):
        raise UnsupportedClassError(class_name)
    if not utils.is_valid_device_id(device_id):
        raise InvalidDeviceIdError()
    filename = await reserve_collect(s, platform, class_name, device_id)
    entry = await get_file(s, platform, filename)
    return PresignedPairResponse(
        filename=filename,
        csv_url=presigned_put_url(entry.csv_bucket, entry.csv_key, CONTENT_TYPES["csv"], PUT_EXPIRES_SECONDS),
        csv_key=entry.csv_key,
        video_url=presigned_put_url(entry.video_bucket, entry.video_key, CONTENT_TYPES["video"], PUT_EXPIRES_SECONDS),
        video_key=entry.video_key,
        expires_in=PUT_EXPIRES_SECONDS,
    )


async def confirm_upload(s: AsyncSession, platform: str, filename: str, video_start: float, rows: int | None) -> UploadConfirmResponse:
    """업로드 2단계, videoStart 검증, 예약 없으면 404"""
    if not utils.is_valid_video_start(video_start):
        raise InvalidVideoStartError()
    if not await confirm_collect(s, platform, filename, video_start, rows):
        raise ReservationNotFoundError()
    return UploadConfirmResponse(filename=filename, status=utils.STATUS_PENDING)


async def files(s: AsyncSession, platform: str) -> ListFilesResponse:
    """목록 전체 조회, 상태별 개수"""
    entries = await list_files(s, platform)
    return ListFilesResponse(platform=platform, files=entries, counts=utils.status_counts(entries))


def _label_objects(entry: CollectFileRead) -> list[tuple[str, str]]:
    """라벨 parquet 영상 pose 객체 위치"""
    if entry.label is None:
        return []
    return [(entry.label.data_bucket, entry.label.data_key), (entry.label.video_bucket, entry.label.video_key),
            (entry.label.data_bucket, entry.label.pose_key)]


def _delete_objects(objects: list[tuple[str, str]]) -> None:
    """S3 객체 목록 삭제"""
    for bucket, key in objects:
        s3.delete_object(bucket, key)


def _rewrite_originals(entry: CollectFileRead, class_name: str, csv_key: str, video_key: str) -> None:
    """새 키에 label 열 바꾼 CSV와 영상, 라벨 후엔 labeled 객체에서 복원"""
    import pandas as pd

    with tempfile.TemporaryDirectory() as workdir:
        src = pathlib.Path(workdir) / "src"
        if entry.label is not None:
            s3.download_object(entry.label.data_bucket, entry.label.data_key, str(src))
            df = pd.read_parquet(src).drop(columns=["phase"], errors="ignore")
        if entry.label is None:
            s3.download_object(entry.csv_bucket, entry.csv_key, str(src))
            df = pd.read_csv(src)
        df.columns = df.columns.str.strip()
        df["label"] = class_name
        out = pathlib.Path(workdir) / "out.csv"
        df.to_csv(out, index=False)
        s3.upload_object(entry.csv_bucket, csv_key, str(out), CONTENT_TYPES["csv"])
    bucket, key = _video_location(entry)
    s3.copy_object(bucket, key, entry.video_bucket, video_key)


async def change_class(s: AsyncSession, platform: str, filename: str, class_name: str) -> CollectFileRead:
    """종목 변경, label 열 바꿔 새 키에 쓰고 행 갱신, 옛 객체와 라벨 삭제, 승격 후 409"""
    entry = await get_file(s, platform, filename)
    if entry is None:
        raise CollectFileNotFoundError(filename)
    if not await is_class_known(s, class_name):
        raise UnsupportedClassError(class_name)
    reason = utils.class_change_block_reason(entry)
    if reason is not None:
        raise ClassChangeBlockedError(filename, reason)
    if entry.class_name == class_name:
        return entry
    changed = await change_collect_class(s, platform, filename, class_name)
    await asyncio.to_thread(_rewrite_originals, entry, class_name, changed.csv_key, changed.video_key)
    await s.commit()
    # ponytail: 옛 객체 삭제 실패는 고아 객체로 남음, 잦으면 정리 배치
    await asyncio.to_thread(_delete_objects, [(entry.csv_bucket, entry.csv_key), (entry.video_bucket, entry.video_key), *_label_objects(entry)])
    return changed


async def delete_file(s: AsyncSession, platform: str, filename: str) -> DeleteFileResponse:
    """수집 파일 삭제, S3 먼저 지워 재시도 가능, 라벨링 중이면 409"""
    entry = await get_file(s, platform, filename)
    if entry is None:
        raise CollectFileNotFoundError(filename)
    if entry.is_labeling:
        raise CollectFileBusyError(filename)
    await asyncio.to_thread(_delete_objects, [(entry.csv_bucket, entry.csv_key), (entry.video_bucket, entry.video_key), *_label_objects(entry)])
    await delete_collect(s, platform, filename)
    await s.commit()
    return DeleteFileResponse(filename=filename)


async def start_labeling(s: AsyncSession, platform: str, filenames: list[str]) -> LabelResponse:
    """라벨링 가능 파일 선별, labeling 표시, 워커 spawn"""
    if not filenames:
        raise EmptyFilenamesError()
    entries = {f.filename: f for f in await list_files(s, platform)}
    accepted, skipped = [], []
    for name in filenames:
        reason = utils.label_block_reason(entries.get(name))
        if reason is not None:
            skipped.append(SkippedFile(filename=name, reason=reason))
            continue
        accepted.append(name)
    if not accepted:
        return LabelResponse(accepted=[], skipped=skipped)

    await mark_labeling(s, platform, accepted)
    await s.commit()
    spawn_worker(platform, accepted)
    return LabelResponse(accepted=accepted, skipped=skipped)


def spawn_worker(platform: str, filenames: list[str]) -> None:
    """phase_labeler 서브프로세스 시작, 로그 임시 파일"""
    log_path = pathlib.Path(tempfile.gettempdir()) / f"phase_labeler_{platform}.log"
    log_file = open(log_path, "a")
    subprocess.Popen(
        [sys.executable, "-m", "app.labeling.worker", "--platform", platform, "--files", json.dumps(filenames)],
        stdout=log_file,
        stderr=log_file,
    )


def _video_location(entry: CollectFileRead) -> tuple[str, str]:
    """영상 위치 선택, 라벨 후 labeled 버킷"""
    if entry.label is not None:
        return entry.label.video_bucket, entry.label.video_key
    return entry.video_bucket, entry.video_key


async def video_url(s: AsyncSession, platform: str, filename: str) -> VideoUrlResponse:
    """영상 재생 presigned GET, 목록에 없으면 404"""
    entry = await get_file(s, platform, filename)
    if entry is None:
        raise CollectFileNotFoundError(filename)
    bucket, key = _video_location(entry)
    return VideoUrlResponse(filename=filename, url=presigned_get_url(bucket, key, GET_EXPIRES_SECONDS), expires_in=GET_EXPIRES_SECONDS)


async def pose(s: AsyncSession, platform: str, filename: str) -> PoseResponse:
    """관절 phase JSON 조회, 라벨 전 404"""
    entry = await get_file(s, platform, filename)
    if entry is None or entry.label is None:
        raise PoseNotReadyError(filename)
    data = await asyncio.to_thread(read_pose, entry.label.data_bucket, entry.label.pose_key)
    return PoseResponse(filename=filename, fps=data["fps"], frames=data["frames"])


def _rewrite_phases(entry: CollectFileRead, pose_data: dict, phases: list[int]) -> list[int]:
    """pose.json 프레임 phase 와 parquet phase 열 덮어쓰기"""
    import numpy as np
    import pandas as pd

    label = entry.label
    with tempfile.TemporaryDirectory() as workdir:
        data_path = pathlib.Path(workdir) / "data.parquet"
        s3.download_object(label.data_bucket, label.data_key, str(data_path))
        df = pd.read_parquet(data_path)
        row_phase = algo.row_phases(df["timestamp"].to_numpy(dtype=float), np.array(phases), pose_data["fps"], float(entry.video_start))
        df["phase"] = np.array(row_phase, dtype=np.int8)
        df.to_parquet(data_path, index=False)
        pose_data["frames"] = [[p, lm] for p, (_, lm) in zip(phases, pose_data["frames"])]
        pose_path = pathlib.Path(workdir) / "pose.json"
        pose_path.write_text(json.dumps(pose_data))
        s3.upload_object(label.data_bucket, label.data_key, str(data_path), CONTENT_TYPES["parquet"])
        s3.upload_object(label.data_bucket, label.pose_key, str(pose_path), "application/json")
    return row_phase


async def edit_phases(s: AsyncSession, platform: str, filename: str, phases: list[int]) -> CollectFileRead:
    """구간 수동 수정, 프레임별 phase 로 pose parquet 요약 갱신"""
    entry = await get_file(s, platform, filename)
    if entry is None or entry.label is None:
        raise PoseNotReadyError(filename)
    reason = utils.class_change_block_reason(entry)
    if reason is not None:
        raise PhaseEditBlockedError(filename, reason)
    pose_data = await asyncio.to_thread(read_pose, entry.label.data_bucket, entry.label.pose_key)
    if len(phases) != len(pose_data["frames"]):
        raise PhaseEditBlockedError(filename, f"프레임 수 {len(pose_data['frames'])}개와 다름")
    row_phase = await asyncio.to_thread(_rewrite_phases, entry, pose_data, phases)
    summary = {**entry.label.phase_summary, **algo.phase_counts(row_phase), "edited": True}
    await update_phase_summary(s, platform, filename, summary)
    await s.commit()
    return await get_file(s, platform, filename)


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


async def promote(s: AsyncSession, platform: str, filenames: list[str]) -> PromoteResponse:
    """승격, DB 행 선점 후 S3 복사, 재실행 시 이어서 완료"""
    if not filenames:
        raise EmptyFilenamesError()
    entries = {f.filename: f for f in await list_files(s, platform)}
    promoted, skipped = [], []
    for name in filenames:
        entry = entries.get(name)
        reason = utils.promote_block_reason(entry)
        if reason is not None:
            skipped.append(SkippedFile(filename=name, reason=reason))
            continue
        key = s3.csv_key(platform, await folder_for(s, entry.class_name), utils.dataset_filename(name))
        dataset = await reserve_promotion(s,
            platform, name, dataset_filename=utils.dataset_filename(name),
            bucket=settings.raw_data_bucket, key=key, phase_labeled=bool(entry.label and entry.label.has_phase),
        )
        await s.commit()
        try:
            await asyncio.to_thread(_copy_to_dataset, entry, dataset.s3_key)
        except (BotoCoreError, ClientError, OSError):
            skipped.append(SkippedFile(filename=name, reason="S3 복사 실패, 다시 승격하면 이어서 진행"))
            continue
        await complete_promotion(s, platform, name)
        await s.commit()
        promoted.append(name)
    return PromoteResponse(promoted=promoted, skipped=skipped)
