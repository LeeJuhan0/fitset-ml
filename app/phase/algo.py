import itertools

import numpy as np

MIN_RUN = 3
PEAK_MIN_RUN = 1


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
    """렙 수, 피크 0 구간 개수"""
    return [k for k, _ in itertools.groupby(seq)].count(0)


def smooth_runs(seq: list[int], min_run: int = MIN_RUN, peak_min_run: int = PEAK_MIN_RUN) -> list[int]:
    """짧은 구간 앞 구간 흡수, 피크 0.1초, 나머지 0.3초"""
    out: list[int] = []
    for value, group in itertools.groupby(seq):
        n = len(list(group))
        need = peak_min_run if value == 0 else min_run
        out += [out[-1] if out and n < need else value] * n
    return out
