from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import s3
from app.core.models import Platform, ensure_device, ensure_platform, find_exercise
from app.exercises.repository import folder_for
from app.data import utils
from app.data.models import DatasetFile, DatasetFileRead

_RESERVE_RETRIES = 5


def download_csv_bytes(bucket: str, key: str) -> bytes:
    """통계용 CSV 본문 메모리 읽기, 목록 행의 위치로"""
    return s3.get_object_bytes(bucket, key)


async def list_files(s: AsyncSession, platform: str) -> list[DatasetFileRead]:
    """dataset_files 전체 조회, Read 변환"""
    rows = (await s.exec(
        select(DatasetFile).join(Platform).where(Platform.name == platform).order_by(DatasetFile.id)
    )).all()
    return [DatasetFileRead.from_row(r) for r in rows]


async def reserve_admin_upload(s: AsyncSession, platform: str, class_name: str, device_id: str) -> tuple[str, str]:
    """예약 행 삽입, 채번, UNIQUE 충돌 재시도"""
    for _ in range(_RESERVE_RETRIES):
        p = await ensure_platform(s, platform)
        device = await ensure_device(s, p, device_id)
        entries = [
            {"filename": r.filename, "class": r.class_name, "deviceId": r.device.device_id}
            for r in (await s.exec(select(DatasetFile).where(DatasetFile.platform_id == p.id))).all()
        ]
        filename = utils.next_filename(entries, class_name, device_id, owner_field="deviceId")
        key = s3._csv_key(platform, await folder_for(s, class_name), filename)
        s.add(DatasetFile(
            platform=p,
            device=device,
            exercise=await find_exercise(s, class_name),
            filename=filename,
            class_name=class_name,
            bucket=s3.settings.raw_data_bucket,
            s3_key=key,
            uploaded=False,
        ))
        try:
            await s.flush()
        except IntegrityError:
            await s.rollback()
            continue
        return filename, key
    raise RuntimeError("파일명 채번 재시도 초과")


async def mark_admin_uploaded(s: AsyncSession, platform: str, filename: str) -> bool:
    """업로드 완료 표시, 없으면 False"""
    row = (await s.exec(
        select(DatasetFile).join(Platform).where(Platform.name == platform, DatasetFile.filename == filename)
    )).first()
    if row is None:
        return False
    row.uploaded = True
    s.add(row)
    return True


def generate_presigned_admin_upload_url(key: str, expires: int = 300) -> str:
    """dataset 버킷 PUT 서명 URL"""
    return s3.presigned_put_url(s3.settings.raw_data_bucket, key, "text/csv", expires)


async def dataset_file_classes(s: AsyncSession, platform: str, filenames: list[str]) -> dict[str, str]:
    """워커용 파일명 → 종목 매핑"""
    rows = (await s.exec(
        select(DatasetFile).join(Platform).where(Platform.name == platform, DatasetFile.filename.in_(filenames))
    )).all()
    return {r.filename: r.class_name for r in rows}


async def mark_trained(s: AsyncSession, platform: str, filenames: list[str], version: str) -> None:
    """워커용 trained_in_version 기록"""
    rows = (await s.exec(
        select(DatasetFile).join(Platform).where(Platform.name == platform, DatasetFile.filename.in_(filenames))
    )).all()
    for r in rows:
        r.trained_in_version = version
        s.add(r)


async def dataset_locations(s: AsyncSession, platform: str, filenames: list[str]) -> dict[str, tuple[str, str]]:
    """워커용 파일명 → (bucket, key), 구·신 폴더 규칙 모두 저장된 키 그대로"""
    rows = (await s.exec(
        select(DatasetFile).join(Platform).where(Platform.name == platform, DatasetFile.filename.in_(filenames))
    )).all()
    return {r.filename: (r.bucket, r.s3_key) for r in rows}
