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
