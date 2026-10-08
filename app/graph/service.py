import asyncio
import io

from sqlmodel.ext.asyncio.session import AsyncSession

from app.data.exceptions import DataFileNotFoundError
from app.data.repository import download_csv_bytes, list_files
from app.graph import utils
from app.graph.schemas import ImuResponse
from app.worker.preprocess import CHANNELS

IMU_MAX_POINTS = 3000


async def file_imu(s: AsyncSession, platform: str, filename: str) -> ImuResponse:
    """학습 CSV 6축 파형, 목록에 없으면 404"""
    entry = next((f for f in await list_files(s, platform) if f.filename == filename), None)
    if entry is None:
        raise DataFileNotFoundError(filename)

    raw = await asyncio.to_thread(download_csv_bytes, entry.bucket, entry.s3_key)
    return ImuResponse(filename=filename, **await asyncio.to_thread(_read_imu_csv, raw))


def _read_imu_csv(raw: bytes) -> dict:
    """CSV 를 시작 기준 초와 6채널로, IMU_MAX_POINTS 이하로 솎음"""
    import pandas as pd

    df = pd.read_csv(io.BytesIO(raw))
    ts = df["timestamp"].astype(float)
    scale = utils.timestamp_scale(float(ts.diff().median()))
    picked = df.iloc[:: max(1, len(df) // IMU_MAX_POINTS)]
    return {
        "t": ((picked["timestamp"].astype(float) - ts.iloc[0]) / scale).round(3).tolist(),
        "channels": {c: picked[c].astype(float).round(4).tolist() for c in CHANNELS},
    }
