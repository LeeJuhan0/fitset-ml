import itertools

import numpy as np


def window_label(y: np.ndarray, num_classes: int = 2) -> int:
    """윈도우 라벨, 범위 밖 제외 다수결, 유효 절반 미만이면 -1"""
    valid = y[(y >= 0) & (y < num_classes)]
    if len(valid) < len(y) // 2:
        return -1
    return int(np.argmax(np.bincount(valid, minlength=num_classes)))


def make_windows(x: np.ndarray, y: np.ndarray, window: int, stride: int) -> tuple[np.ndarray, np.ndarray]:
    """슬라이딩 윈도우, 라벨 -1 윈도우 제외"""
    xs, ys = [], []
    for s in range(0, len(x) - window + 1, stride):
        lab = window_label(y[s:s + window])
        if lab < 0:
            continue
        xs.append(x[s:s + window])
        ys.append(lab)
    return np.array(xs, dtype=np.float32).reshape(-1, window, x.shape[1]), np.array(ys, dtype=np.int64)


def count_reps(seq: list[int]) -> int:
    """렙 수, 0·1 구간 수 중 작은 쪽"""
    runs = [k for k, _ in itertools.groupby(seq)]
    return min(runs.count(0), runs.count(1))


def row_predictions(preds: list[int], n_rows: int, window: int, stride: int) -> np.ndarray:
    """윈도우 예측 → 행별 예측, 윈도우 중심 ±stride/2 에 배정, 밖은 -1"""
    out = np.full(n_rows, -1, dtype=int)
    for i, p in enumerate(preds):
        c = i * stride + window // 2
        out[max(0, c - stride // 2):c + stride - stride // 2] = p
    return out


def frame_values(timestamps: np.ndarray, row_values: np.ndarray, fps: float, video_start: float, n_frames: int) -> list[int]:
    """행 값 → 영상 프레임 값, 가장 가까운 행, IMU 범위 밖은 -1"""
    t = video_start + np.arange(n_frames) / fps
    j = np.clip(np.searchsorted(timestamps, t), 1, len(timestamps) - 1)
    j = np.where(np.abs(timestamps[j - 1] - t) <= np.abs(timestamps[j] - t), j - 1, j)
    out = row_values[j].astype(int)
    out[(t < timestamps[0]) | (t > timestamps[-1])] = -1
    return out.tolist()
