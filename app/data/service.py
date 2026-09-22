import asyncio
import io

from sqlmodel.ext.asyncio.session import AsyncSession

from app.data import utils
from app.core.schemas import FilenameQuery
from app.data.schemas import FileStatsData, ListDataData, PresignedUrlData, PresignedUrlQuery, UploadConfirmData, UploadConfirmRequest
from app.exercises.repository import is_class_known
from app.data.exceptions import DataFileNotFoundError, InvalidDeviceIdError, ReservationNotFoundError, UnsupportedClassError

from app.data.repository import (
    download_csv_bytes,
    generate_presigned_admin_upload_url,
    list_files,
    mark_admin_uploaded,
    reserve_admin_upload,
)


PRESIGNED_EXPIRES_SECONDS = 300
STATS_TRIM_SECONDS = 3.0
SENSOR_CHANNELS = ["ax", "ay", "az", "gx", "gy", "gz"]


async def list_data(s: AsyncSession, platform: str) -> ListDataData:
    """학습 데이터셋 목록 목록"""
    return ListDataData.model_validate({"platform": platform, "files": await list_files(s, platform)})


async def file_stats(s: AsyncSession, platform: str, query: FilenameQuery) -> FileStatsData:
    """센서 CSV 채널별 통계, 목록에 없으면 404"""
    filename = query.filename

    entry = next((f for f in await list_files(s, platform) if f.filename == filename), None)
    if entry is None:
        raise DataFileNotFoundError(filename)

    raw = await asyncio.to_thread(download_csv_bytes, entry.bucket, entry.s3_key)
    return await asyncio.to_thread(_compute_stats, raw, filename, entry.class_name)


def _compute_stats(raw: bytes, filename: str, class_name: str) -> FileStatsData:
    """CSV 파싱, 앞뒤 트림, 채널별 통계, 동기 CPU 작업"""
    import pandas as pd

    df = pd.read_csv(io.BytesIO(raw))
    t = (df["timestamp"] - df["timestamp"].iloc[0]) / 1e9
    duration = float(t.iloc[-1])
    trimmed = df[(t >= STATS_TRIM_SECONDS) & (t <= duration - STATS_TRIM_SECONDS)]
    trim_applied = len(trimmed) > 0
    used = trimmed if trim_applied else df
    return FileStatsData.model_validate({
        "filename": filename,
        "class": class_name,
        "trim_seconds": STATS_TRIM_SECONDS,
        "trim_applied": trim_applied,
        "duration_seconds": round(duration, 1),
        "total_rows": int(len(df)),
        "used_rows": int(len(used)),
        "channels": [
            {
                "channel": c,
                "mean": round(float(used[c].mean()), 4),
                "min": round(float(used[c].min()), 4),
                "max": round(float(used[c].max()), 4),
                "std": round(float(used[c].std()), 4),
            }
            for c in SENSOR_CHANNELS
        ],
    })


async def admin_issue_upload_url(s: AsyncSession, platform: str, query: PresignedUrlQuery) -> PresignedUrlData:
    """어드민 직행 업로드 1단계, 검증 채번 presigned PUT"""
    class_name, device_id = query.class_name, query.device_id
    if not await is_class_known(s, class_name):
        raise UnsupportedClassError(class_name)
    if not utils.is_valid_device_id(device_id):
        raise InvalidDeviceIdError()
    filename, key = await reserve_admin_upload(s, platform, class_name, device_id)
    url = generate_presigned_admin_upload_url(key)
    return PresignedUrlData.model_validate({
        "presignedUrl": url,
        "expiresIn": PRESIGNED_EXPIRES_SECONDS,
        "s3Key": key,
        "filename": filename,
    })


async def admin_confirm_upload(s: AsyncSession, platform: str, payload: UploadConfirmRequest) -> UploadConfirmData:
    """어드민 업로드 확정, 종목 검증, 예약 없으면 404"""
    class_name, filename = payload.class_name, payload.filename
    if not await is_class_known(s, class_name):
        raise UnsupportedClassError(class_name)
    if not await mark_admin_uploaded(s, platform, filename):
        raise ReservationNotFoundError()
    return UploadConfirmData.model_validate({"filename": filename, "class": class_name})
