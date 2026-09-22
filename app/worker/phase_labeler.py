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
from app.phase.models import CollectFileRead
from app.exercises.repository import phase_rule
from app.phase.repository import finish_label, get_file, set_status
from app.worker import phase_algo as algo


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


def extract_pose(video_path: str, joints: tuple | None) -> tuple[np.ndarray, list, float]:
    """MediaPipe 프레임별 각도, 랜드마크 33개, 회전 자동"""
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
    angles, landmarks = [], []
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        rgb = np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        res = landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), int(i * 1000 / fps))
        i += 1
        if not res.pose_landmarks:
            angles.append(np.nan)
            landmarks.append(None)
            continue
        lm = res.pose_landmarks[0]
        world = res.pose_world_landmarks[0]
        landmarks.append([[round(p.x, 3), round(p.y, 3), round(p.visibility, 2)] for p in lm])
        if joints is None:
            angles.append(np.nan)
            continue
        vis = np.mean([lm[algo.LM[j][algo.SIDE]].visibility for j in joints])
        if vis < algo.MIN_VISIBILITY:
            angles.append(np.nan)
            continue
        pts = [np.array([world[algo.LM[j][algo.SIDE]].x, world[algo.LM[j][algo.SIDE]].y, world[algo.LM[j][algo.SIDE]].z]) for j in joints]
        angles.append(algo.angle(*pts))
    cap.release()
    landmarker.close()
    return np.array(angles, dtype=float), landmarks, fps


def label_file(platform: str, entry: CollectFileRead, workdir: str) -> dict:
    """다운로드, 추출, phase 부착, labeled 버킷 업로드 복사"""
    filename, class_name = entry.filename, entry.class_name
    stem = filename[:-4]
    rule = db.run(_with_session(phase_rule, class_name))
    joints, down_is_decreasing = rule if rule is not None else (None, True)
    csv_path = os.path.join(workdir, filename)
    video_path = os.path.join(workdir, stem + VIDEO_EXT)
    s3.download_object(entry.csv_bucket, entry.csv_key, csv_path)
    s3.download_object(entry.video_bucket, entry.video_key, video_path)

    angles, landmarks, fps = extract_pose(video_path, joints)
    phase = algo.phases_from_angles(angles, fps, down_is_decreasing)
    df = pd.read_csv(csv_path)
    df.columns = df.columns.str.strip()
    row_phase = algo.row_phases(df["timestamp"].to_numpy(dtype=float), phase, fps, float(entry.video_start))
    df["phase"] = np.array(row_phase, dtype=np.int8)
    summary = algo.summarize(angles, fps, row_phase)
    summary["hasPhase"] = rule is not None

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
    s3.copy_object(entry.video_bucket, entry.video_key, dst)
    return {"summary": summary, "data_key": data_key, "pose_key": pose_key}


def move_to_labeled(platform: str, entry: CollectFileRead, result: dict) -> None:
    """목록 완료 기록, 원본 객체 삭제"""
    dst = settings.collect_labeled_bucket
    db.run(_with_session(
        finish_label, platform, entry.filename,
        data_bucket=dst, data_key=result["data_key"],
        video_bucket=dst, video_key=entry.video_key,
        pose_key=result["pose_key"], phase_summary=result["summary"],
    ))
    s3.delete_object(entry.csv_bucket, entry.csv_key)
    s3.delete_object(entry.video_bucket, entry.video_key)


def run(platform: str, filenames: list[str]) -> None:
    """파일별 독립 처리, 실패 시 failed 기록"""
    db.run(db.init_db())
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
