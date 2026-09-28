import json

from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import s3
from app.core.models import Platform, ensure_device, ensure_platform, find_exercise
from app.exercises.repository import folder_for
from app.data.models import DatasetFile, DatasetFileRead
from app.labeling import utils
from app.core.utils import utcnow
from app.labeling.models import CollectFile, CollectFileRead, PhaseLabel

_RESERVE_RETRIES = 5
CONTENT_TYPES = {"csv": "text/csv", "video": "video/quicktime", "pose": "application/json", "parquet": "application/vnd.apache.parquet"}


async def list_files(s: AsyncSession, platform: str) -> list[CollectFileRead]:
    """collect_files 전체 조회, Read 변환"""
    rows = (await s.exec(
        select(CollectFile).join(Platform).where(Platform.name == platform).order_by(CollectFile.id)
    )).all()
    return [CollectFileRead.from_row(r) for r in rows]


async def _row(s: AsyncSession, platform: str, filename: str) -> CollectFile | None:
    """플랫폼 파일명으로 행 하나"""
    return (await s.exec(
        select(CollectFile).join(Platform).where(Platform.name == platform, CollectFile.filename == filename)
    )).first()


async def get_file(s: AsyncSession, platform: str, filename: str) -> CollectFileRead | None:
    """행 하나 조회, Read 변환"""
    row = await _row(s, platform, filename)
    return CollectFileRead.from_row(row) if row is not None else None


async def _next_filename(s: AsyncSession, platform_id: int, class_name: str, device_id: str) -> str:
    """플랫폼 기존 행 기준 다음 파일명"""
    entries = [
        {"filename": r.filename, "class": r.class_name, "deviceId": r.device.device_id}
        for r in (await s.exec(select(CollectFile).where(CollectFile.platform_id == platform_id))).all()
    ]
    return utils.next_filename(entries, class_name, device_id, owner_field="deviceId")


async def reserve_collect(s: AsyncSession, platform: str, class_name: str, device_id: str) -> str:
    """예약 행 삽입, 채번, UNIQUE 충돌 재시도"""
    for _ in range(_RESERVE_RETRIES):
        p = await ensure_platform(s, platform)
        device = await ensure_device(s, p, device_id)
        filename = await _next_filename(s, p.id, class_name, device_id)
        folder = await folder_for(s, class_name)
        s.add(CollectFile(
            platform=p,
            device=device,
            exercise=await find_exercise(s, class_name),
            filename=filename,
            class_name=class_name,
            csv_bucket=s3.settings.collect_imu_bucket,
            csv_key=s3.collect_key(platform, folder, filename),
            video_bucket=s3.settings.collect_video_bucket,
            video_key=s3.collect_key(platform, folder, utils.video_name(filename)),
            uploaded=False,
            status=utils.STATUS_PENDING,
        ))
        try:
            await s.flush()
        except IntegrityError:
            await s.rollback()
            continue
        return filename
    raise RuntimeError("파일명 채번 재시도 초과")


async def confirm_collect(s: AsyncSession, platform: str, filename: str, video_start: float, rows: int | None) -> bool:
    """업로드 완료 표시, videoStart rows 기록"""
    row = await _row(s, platform, filename)
    if row is None:
        return False
    row.uploaded = True
    row.video_start = video_start
    row.rows = rows
    row.status = utils.STATUS_PENDING
    row.error = None
    s.add(row)
    return True


async def delete_collect(s: AsyncSession, platform: str, filename: str) -> None:
    """수집 행과 라벨 행 삭제, 승격 사본은 유지"""
    row = await _row(s, platform, filename)
    if row is None:
        return
    if row.label is not None:
        await s.delete(row.label)
    await s.delete(row)


async def change_collect_class(s: AsyncSession, platform: str, filename: str, class_name: str) -> CollectFileRead:
    """종목 변경, 새 파일명과 키 채번, 라벨 초기화"""
    row = await _row(s, platform, filename)
    new_name = await _next_filename(s, row.platform_id, class_name, row.device.device_id)
    folder = await folder_for(s, class_name)
    if row.label is not None:
        await s.delete(row.label)
        row.label = None
    row.filename = new_name
    row.class_name = class_name
    row.exercise = await find_exercise(s, class_name)
    row.csv_key = s3.collect_key(platform, folder, new_name)
    row.video_key = s3.collect_key(platform, folder, utils.video_name(new_name))
    row.status = utils.STATUS_PENDING
    row.error = None
    s.add(row)
    await s.flush()
    return CollectFileRead.from_row(row)


async def mark_labeling(s: AsyncSession, platform: str, filenames: list[str]) -> None:
    """선택 파일 labeling 상태 전이"""
    rows = (await s.exec(
        select(CollectFile).join(Platform).where(Platform.name == platform, CollectFile.filename.in_(filenames))
    )).all()
    for r in rows:
        r.status = utils.STATUS_LABELING
        r.error = None
        s.add(r)


def presigned_put_url(bucket: str, key: str, content_type: str, expires: int) -> str:
    """S3 PUT 서명 URL"""
    return s3.presigned_put_url(bucket, key, content_type, expires)


def presigned_get_url(bucket: str, key: str, expires: int) -> str:
    """S3 GET 서명 URL"""
    return s3.presigned_get_url(bucket, key, expires)


def read_pose(bucket: str, key: str) -> dict:
    """pose.json 객체 읽기, dict"""
    return json.loads(s3.get_object_bytes(bucket, key))


async def set_status(s: AsyncSession, platform: str, filename: str, status: str, error: str | None = None) -> None:
    """워커용 상태 전이, error 기록"""
    row = await _row(s, platform, filename)
    if row is None:
        return
    row.status = status
    row.error = error
    s.add(row)


async def finish_label(s: AsyncSession, platform: str, filename: str, *, data_bucket: str, data_key: str,
                 video_bucket: str, video_key: str, pose_key: str, phase_summary: dict) -> None:
    """워커용 완료 처리, phase_labels upsert, labeled 전이"""
    row = await _row(s, platform, filename)
    if row is None:
        return
    label = row.label or PhaseLabel(collect_file=row)
    label.data_bucket = data_bucket
    label.data_key = data_key
    label.video_bucket = video_bucket
    label.video_key = video_key
    label.pose_key = pose_key
    label.phase_summary = phase_summary
    label.labeled_at = utcnow()
    row.rows = phase_summary.get("rows", row.rows)
    row.status = utils.STATUS_LABELED
    row.error = None
    s.add(label)
    s.add(row)


async def reserve_promotion(s: AsyncSession, platform: str, filename: str, *, dataset_filename: str, bucket: str, key: str, phase_labeled: bool) -> DatasetFileRead:
    """승격 1단계, uploaded False 행 선점, 재시도면 기존 행"""
    row = await _row(s, platform, filename)
    if row.dataset_file is not None:
        return DatasetFileRead.from_row(row.dataset_file)
    dataset = DatasetFile(
        platform=row.platform,
        device=row.device,
        exercise=row.exercise,
        filename=dataset_filename,
        class_name=row.class_name,
        bucket=bucket,
        s3_key=key,
        uploaded=False,
        phase_labeled=phase_labeled,
    )
    s.add(dataset)
    await s.flush()
    row.dataset_file = dataset
    s.add(row)
    await s.flush()
    return DatasetFileRead.from_row(dataset)


async def complete_promotion(s: AsyncSession, platform: str, filename: str) -> None:
    """승격 2단계, S3 복사 후 uploaded True, promoted_at"""
    row = await _row(s, platform, filename)
    row.dataset_file.uploaded = True
    row.promoted_at = utcnow()
    s.add(row.dataset_file)
    s.add(row)
