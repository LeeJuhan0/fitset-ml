import argparse
import json
import os
import tempfile
import traceback
import urllib.request

import numpy as np
import pandas as pd

from app.core import db, s3
from app.core.config import settings
from app.labeling.models import CollectFileRead
from app.motions.utils import load_motion
from app.labeling.repository import finish_label, get_file, set_status
from app.labeling import algo


async def _with_session(fn, *args, **kwargs):
    """워커용, 세션 하나 열어 repository 코루틴 실행"""
    async with db.session() as s:
        return await fn(s, *args, **kwargs)

POSE_MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
                  "pose_landmarker_full/float16/latest/pose_landmarker_full.task")
VIDEO_EXT = ".mov"
POSE_EXT = ".pose.json"
DATA_EXT = ".parquet"


def ensure_model() -> str:
    """포즈 모델 경로 확인, 없으면 다운로드"""
    path = settings.pose_model_path
    if os.path.exists(path):
        return path
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    urllib.request.urlretrieve(POSE_MODEL_URL, path)
    return path


def extract_pose(video_path: str, motion) -> tuple[np.ndarray, list, float]:
    """MediaPipe 프레임별 판정 신호, 랜드마크 33개, 회전 자동"""
    import cv2
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    opts = vision.PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=ensure_model()),
        running_mode=vision.RunningMode.VIDEO,
        min_pose_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    landmarker = vision.PoseLandmarker.create_from_options(opts)
    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_ORIENTATION_AUTO, 1)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    world, image, vis, landmarks = [], [], [], []
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        rgb = np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        res = landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), int(i * 1000 / fps))
        i += 1
        if not res.pose_landmarks:
            world.append(np.full((33, 3), np.nan))
            image.append(np.full((33, 3), np.nan))
            vis.append(np.zeros(33))
            landmarks.append(None)
            continue
        lm = res.pose_landmarks[0]
        aspect = frame.shape[1] / frame.shape[0]
        landmarks.append([[round(p.x, 3), round(p.y, 3), round(p.visibility, 2)] for p in lm])
        world.append([[p.x, p.y, p.z] for p in res.pose_world_landmarks[0]])
        image.append([[p.x * aspect, p.y, 0.0] for p in lm])
        vis.append([p.visibility for p in lm])
    cap.release()
    landmarker.close()
    return motion_signal(motion, np.array(world, dtype=float), np.array(image, dtype=float), np.array(vis, dtype=float)), landmarks, fps


def motion_signal(motion, world: np.ndarray, image: np.ndarray, vis: np.ndarray) -> np.ndarray:
    """종목 판정 신호, 관절 가시성 낮은 프레임 NaN"""
    if motion is None or len(world) == 0:
        return np.full(len(world), np.nan)
    signal = np.asarray(motion.signal(world, image), dtype=float)
    signal[vis[:, list(motion.LANDMARKS)].mean(axis=1) < algo.MIN_VISIBILITY] = np.nan
    return signal


def download_sources(entry: CollectFileRead, workdir: str) -> tuple[pd.DataFrame, str]:
    """IMU 표와 영상 경로, 재라벨은 labeled 객체에서"""
    video_path = os.path.join(workdir, entry.filename[:-4] + VIDEO_EXT)
    src_path = os.path.join(workdir, "src")
    if entry.label is not None:
        s3.download_object(entry.label.data_bucket, entry.label.data_key, src_path)
        s3.download_object(entry.label.video_bucket, entry.label.video_key, video_path)
        return pd.read_parquet(src_path).drop(columns=["phase"], errors="ignore"), video_path
    s3.download_object(entry.csv_bucket, entry.csv_key, src_path)
    s3.download_object(entry.video_bucket, entry.video_key, video_path)
    df = pd.read_csv(src_path)
    df.columns = df.columns.str.strip()
    return df, video_path


def label_file(platform: str, entry: CollectFileRead, workdir: str) -> dict:
    """다운로드, 추출, phase 부착, labeled 버킷 업로드 복사"""
    stem = entry.filename[:-4]
    motion = load_motion(entry.class_name)
    df, video_path = download_sources(entry, workdir)

    angles, landmarks, fps = extract_pose(video_path, motion)
    phase = algo.phases_from_angles(angles, fps, motion.DOWN_IS_DECREASING if motion is not None else True)
    row_phase = algo.row_phases(df["timestamp"].to_numpy(dtype=float), phase, fps, float(entry.video_start))
    df["phase"] = np.array(row_phase, dtype=np.int8)
    summary = algo.summarize(angles, fps, row_phase)
    summary["hasPhase"] = motion is not None

    data_path = os.path.join(workdir, stem + DATA_EXT)
    df.to_parquet(data_path, index=False)
    pose_path = os.path.join(workdir, stem + POSE_EXT)
    with open(pose_path, "w") as f:
        json.dump({"fps": round(fps, 3), "frames": [[int(p), lm] for p, lm in zip(phase, landmarks)]}, f)

    dst = settings.collect_labeled_bucket
    folder = os.path.dirname(entry.csv_key)
    data_key = f"{folder}/{stem}{DATA_EXT}"
    pose_key = f"{folder}/{stem}{POSE_EXT}"
    s3.upload_object(dst, data_key, data_path, "application/vnd.apache.parquet")
    s3.upload_object(dst, pose_key, pose_path, "application/json")
    if entry.label is None:
        s3.copy_object(entry.video_bucket, entry.video_key, dst)
    return {"summary": summary, "data_key": data_key, "pose_key": pose_key}


def move_to_labeled(platform: str, entry: CollectFileRead, result: dict) -> None:
    """재라벨은 승격본 먼저 갱신, 목록 완료 기록, 첫 라벨은 원본 삭제"""
    dst = settings.collect_labeled_bucket
    ds = entry.dataset_file
    if entry.label is not None and ds is not None and ds.uploaded:
        s3.copy_object(dst, result["data_key"], ds.bucket, ds.s3_key)
    db.run(_with_session(
        finish_label, platform, entry.filename,
        data_bucket=dst, data_key=result["data_key"],
        video_bucket=dst, video_key=entry.video_key,
        pose_key=result["pose_key"], phase_summary=result["summary"],
    ))
    if entry.label is None:
        s3.delete_object(entry.csv_bucket, entry.csv_key)
        s3.delete_object(entry.video_bucket, entry.video_key)


def run(platform: str, filenames: list[str]) -> None:
    """파일별 독립 처리, 실패 시 failed 기록"""
    for filename in filenames:
        entry = db.run(_with_session(get_file, platform, filename))
        if entry is None:
            print(f"SKIP {filename}: 목록에 없음", flush=True)
            continue
        with tempfile.TemporaryDirectory() as workdir:
            try:
                result = label_file(platform, entry, workdir)
                move_to_labeled(platform, entry, result)
                print(f"DONE {filename} {json.dumps(result['summary'])}", flush=True)
            except Exception as e:
                db.run(_with_session(set_status, platform, filename, "failed", f"{type(e).__name__}: {e}"[-500:]))
                print(f"FAIL {filename}\n{traceback.format_exc()}", flush=True)


def main():
    """CLI 인자, platform, files JSON"""
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", required=True)
    ap.add_argument("--files", required=True, help="JSON 배열 문자열")
    args = ap.parse_args()
    run(args.platform, json.loads(args.files))


if __name__ == "__main__":
    main()
