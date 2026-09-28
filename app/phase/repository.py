
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import s3
from app.core.models import Platform, ensure_platform, find_exercise
from app.deployment.repository import add_deployment
from app.data.models import DatasetFile, DatasetFileRead
from app.phase import utils
from app.core.utils import utcnow
from app.phase.models import PhaseModel, PhaseModelFile, PhaseModelRead


async def phase_labeled_files(s: AsyncSession, platform: str, class_name: str) -> list[DatasetFileRead]:
    """렙카운팅 학습 후보, 종목의 phase_labeled 업로드 완료 파일"""
    rows = (await s.exec(
        select(DatasetFile).join(Platform).where(
            Platform.name == platform, DatasetFile.class_name == class_name,
            DatasetFile.phase_labeled.is_(True), DatasetFile.uploaded.is_(True),
        ).order_by(DatasetFile.id)
    )).all()
    return [DatasetFileRead.from_row(r) for r in rows]


async def phase_model_versions(s: AsyncSession, platform: str, class_name: str) -> list[str]:
    """종목의 기존 모델 버전 목록"""
    return list((await s.exec(
        select(PhaseModel.version).join(Platform).where(Platform.name == platform, PhaseModel.class_name == class_name)
    )).all())


async def create_phase_model(s: AsyncSession, platform: str, class_name: str, version: str, filenames: list[str], *,
                       window: int, stride: int, epochs: int, lr: float = 0.001) -> PhaseModelRead:
    """phase_models 행 삽입, 학습 파일 링크, status training"""
    p = await ensure_platform(s, platform)
    files = (await s.exec(
        select(DatasetFile).where(DatasetFile.platform_id == p.id, DatasetFile.filename.in_(filenames))
    )).all()
    row = PhaseModel(
        platform=p, exercise=await find_exercise(s, class_name), class_name=class_name, version=version, bucket=s3.settings.phase_models_bucket,
        window=window, stride=stride, epochs=epochs, lr=lr, num_files=len(files),
    )
    s.add(row)
    await s.flush()
    for f in files:
        s.add(PhaseModelFile(phase_model_id=row.id, dataset_file_id=f.id))
    await s.flush()
    return PhaseModelRead.from_row(row)


async def list_phase_models(s: AsyncSession, platform: str, class_name: str | None = None) -> list[PhaseModelRead]:
    """모델 목록, 종목 필터, 최신순"""
    stmt = select(PhaseModel).join(Platform).where(Platform.name == platform)
    if class_name is not None:
        stmt = stmt.where(PhaseModel.class_name == class_name)
    rows = (await s.exec(stmt.order_by(PhaseModel.id.desc()))).all()
    return [PhaseModelRead.from_row(r) for r in rows]


async def get_phase_model(s: AsyncSession, platform: str, model_id: int) -> PhaseModelRead | None:
    """모델 하나 조회"""
    row = (await s.exec(select(PhaseModel).join(Platform).where(Platform.name == platform, PhaseModel.id == model_id))).first()
    return PhaseModelRead.from_row(row) if row is not None else None


async def deploy_phase_model(s: AsyncSession, platform: str, model_id: int) -> PhaseModelRead | None:
    """배포 표시, 같은 종목 기존 배포 해제"""
    row = (await s.exec(select(PhaseModel).join(Platform).where(Platform.name == platform, PhaseModel.id == model_id))).first()
    if row is None:
        return None
    others = (await s.exec(select(PhaseModel).where(
        PhaseModel.platform_id == row.platform_id, PhaseModel.class_name == row.class_name,
        PhaseModel.deployed_at.is_not(None), PhaseModel.id != row.id,
    ))).all()
    for other in others:
        other.deployed_at = None
        s.add(other)
    row.deployed_at = utcnow()
    s.add(row)
    await add_deployment(
        s, platform, kind="phase", class_name=row.class_name, version=row.version, bucket=row.bucket,
        model_key=row.mlpackage_key if platform == "ios" else row.onnx_key, meta_key=row.meta_key,
    )
    return PhaseModelRead.from_row(row)


async def deployed_phase_models(s: AsyncSession, platform: str) -> list[PhaseModelRead]:
    """종목별 배포 모델, 종목순"""
    rows = (await s.exec(
        select(PhaseModel).join(Platform).where(Platform.name == platform, PhaseModel.deployed_at.is_not(None)).order_by(PhaseModel.class_name)
    )).all()
    return [PhaseModelRead.from_row(r) for r in rows]


async def finish_phase_model(s: AsyncSession, model_id: int, *, keys: dict, metrics: dict, mlflow_run_id: str) -> None:
    """워커용 완료 처리, 산출물 키, 지표, completed"""
    row = await s.get(PhaseModel, model_id)
    if row is None:
        return
    row.pt_key = keys.get("pt_key")
    row.onnx_key = keys.get("onnx_key")
    row.mlpackage_key = keys.get("mlpackage_key")
    row.meta_key = keys.get("meta_key")
    row.metrics = metrics
    row.mlflow_run_id = mlflow_run_id
    row.status = utils.MODEL_STATUS_COMPLETED
    row.error = None
    s.add(row)


async def fail_phase_model(s: AsyncSession, model_id: int, error: str) -> None:
    """워커용 실패 처리, failed, error"""
    row = await s.get(PhaseModel, model_id)
    if row is None:
        return
    row.status = utils.MODEL_STATUS_FAILED
    row.error = error
    s.add(row)
