import asyncio
import json
import os
import pathlib
import subprocess
import sys
import tempfile

from sqlmodel.ext.asyncio.session import AsyncSession

from app.phase.schemas import ListModelsResponse, ModelUrlResponse, PhaseTrainResponse, PredictResponse
from app.core import s3
from app.core.s3 import presigned_get_url
from app.core.utils import LOST_PROCESS_ERROR, exit_error, read_tail
from app.labeling.exceptions import PoseNotReadyError
from app.labeling.models import CollectFileRead
from app.labeling.repository import get_file
from app.labeling.utils import dataset_filename
from app.phase import algo, utils
from app.phase.exceptions import (
    InvalidModelFormatError,
    ModelArtifactNotFoundError,
    NoPhaseLabeledFilesError,
    UnknownPhaseFilesError,
    UnsupportedPhaseClassError,
)
from app.motions.utils import load_motion
from app.phase.models import PhaseModelRead
from app.phase.repository import (
    create_phase_model,
    deploy_phase_model,
    fail_phase_model,
    get_phase_model,
    list_phase_models,
    phase_labeled_files,
    phase_model_versions,
)

_trainer_procs: dict[int, subprocess.Popen] = {}
GET_EXPIRES_SECONDS = 3600


async def start_phase_training(s: AsyncSession, platform: str, class_name: str, filenames: list[str] | None, *, epochs: int, lr: float, window: int, stride: int) -> PhaseTrainResponse:
    """종목 검증, 파일 확정, 버전 채번, 워커 spawn"""
    if load_motion(class_name) is None:
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
    spawn_trainer(platform, class_name, model.id, version, chosen, window=window, stride=stride, epochs=epochs, lr=lr)
    await s.commit()
    return PhaseTrainResponse(model_id=model.id, version=version, class_name=class_name, num_files=len(chosen))


def spawn_trainer(platform: str, class_name: str, model_id: int, version: str, filenames: list[str], *,
                  window: int, stride: int, epochs: int, lr: float) -> None:
    """phase_trainer 서브프로세스 시작, 종료 판정용 보관"""
    log_file = open(_trainer_log_path(platform, class_name, version), "w")
    _trainer_procs[model_id] = subprocess.Popen(
        [sys.executable, "-u", "-m", "app.phase.worker", "--platform", platform, "--class", class_name,
         "--model-id", str(model_id), "--version", version, "--files", json.dumps(filenames),
         "--window", str(window), "--stride", str(stride), "--epochs", str(epochs), "--lr", str(lr)],
        stdout=log_file,
        stderr=log_file,
    )


def _trainer_log_path(platform: str, class_name: str, version: str) -> pathlib.Path:
    """phase_trainer 로그 경로"""
    return pathlib.Path(tempfile.gettempdir()) / f"phase_trainer_{platform}_{class_name}_{version}.log"


async def reconcile_training(s: AsyncSession, platform: str) -> None:
    """training 행의 워커 종료 판정, 죽었으면 failed 와 사유"""
    for m in await list_phase_models(s, platform):
        if not m.is_training:
            continue
        proc = _trainer_procs.get(m.id)
        if proc is not None and proc.poll() is None:
            continue
        _trainer_procs.pop(m.id, None)
        if proc is not None and proc.returncode == 0:
            continue
        error = LOST_PROCESS_ERROR if proc is None else exit_error(proc.returncode, read_tail(_trainer_log_path(platform, m.class_name, m.version)))
        await fail_phase_model(s, m.id, error)
    await s.commit()


async def models(s: AsyncSession, platform: str, class_name: str | None) -> ListModelsResponse:
    """종료 판정 후 모델 목록"""
    await reconcile_training(s, platform)
    return ListModelsResponse(platform=platform, models=await list_phase_models(s, platform, class_name))


async def model_download_url(s: AsyncSession, platform: str, model_id: int, fmt: str) -> ModelUrlResponse:
    """산출물 presigned GET, 포맷 검증, 미완성이면 404"""
    if not utils.is_valid_model_format(fmt):
        raise InvalidModelFormatError()
    model = await get_phase_model(s, platform, model_id)
    if model is None or not model.can_download:
        raise ModelArtifactNotFoundError()
    key = {"pt": model.pt_key, "onnx": model.onnx_key, "mlpackage": model.mlpackage_key}[fmt]
    if key is None:
        raise ModelArtifactNotFoundError()
    return ModelUrlResponse(model_id=model_id, format=fmt, url=presigned_get_url(model.bucket, key, GET_EXPIRES_SECONDS), expires_in=GET_EXPIRES_SECONDS)


async def deploy_model(s: AsyncSession, platform: str, model_id: int, env: str) -> PhaseModelRead:
    """렙카운팅 모델 환경별 배포, 롤백 겸용, 파일 없으면 404"""
    model = await get_phase_model(s, platform, model_id)
    if model is None or not model.can_download:
        raise ModelArtifactNotFoundError()
    if (model.mlpackage_key if platform == "ios" else model.onnx_key) is None:
        raise ModelArtifactNotFoundError()
    return await deploy_phase_model(s, platform, model_id, env)



def _predict(model: PhaseModelRead, entry: CollectFileRead) -> dict:
    """pt meta 라벨 parquet 받아 학습 평가와 같은 추론, 프레임에 맞춤"""
    import numpy as np
    import torch

    from app.phase.worker import INFER_STRIDE, VAL_FRAC, infer_sequence
    from app.worker.model_def import FitSetModel
    from app.worker.preprocess import CHANNELS, load_table

    meta = json.loads(s3.get_object_bytes(model.bucket, model.meta_key))
    with tempfile.TemporaryDirectory() as workdir:
        pt_path = os.path.join(workdir, "model.pt")
        s3.download_object(model.bucket, model.pt_key, pt_path)
        data_path = os.path.join(workdir, "data.parquet")
        s3.download_object(entry.label.data_bucket, entry.label.data_key, data_path)
        net = FitSetModel(num_classes=len(meta["classes"]))
        net.load_state_dict(torch.load(pt_path, map_location="cpu", weights_only=True))
        df = load_table(data_path)
    net.eval()
    x = df[CHANNELS].to_numpy(dtype=np.float32)
    y = df["phase"].to_numpy(dtype=int) if "phase" in df else np.full(len(df), -1)
    ts = df["timestamp"].to_numpy(dtype=float)
    window = meta["window"]
    preds = infer_sequence(net, x, np.array(meta["mean"], np.float32), np.array(meta["std"], np.float32), window, "cpu")

    fps, n_frames, start = entry.label.phase_summary["fps"], entry.label.phase_summary["frames"], float(entry.video_start)
    row_pred = algo.row_predictions(preds, len(x), window, INFER_STRIDE)
    val_start_frame = None
    if dataset_filename(entry.filename) in meta.get("trained_files", []):
        val_start_frame = int(round((ts[int(len(x) * (1 - VAL_FRAC))] - start) * fps))
    return {
        "fps": fps,
        "frames": algo.frame_values(ts, row_pred, fps, start, n_frames),
        "label_count": algo.count_reps([int(v) for v in y if v >= 0]),
        "model_count": algo.count_reps(preds),
        "val_start_frame": val_start_frame,
    }


async def predict(s: AsyncSession, platform: str, model_id: int, filename: str) -> PredictResponse:
    """라벨된 수집 파일에 모델 추론, 모델 미완성 또는 라벨 전이면 404"""
    model = await get_phase_model(s, platform, model_id)
    if model is None or not model.can_download or model.meta_key is None:
        raise ModelArtifactNotFoundError()
    entry = await get_file(s, platform, filename)
    if entry is None or entry.label is None:
        raise PoseNotReadyError(filename)
    out = await asyncio.to_thread(_predict, model, entry)
    return PredictResponse(model_id=model_id, version=model.version, filename=filename, **out)
