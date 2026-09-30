import numpy as np

from scipy.signal import find_peaks, savgol_filter

from app.phase.algo import count_reps

SMOOTH_SECONDS = 0.3
DETECT_GAP_SECONDS = 0.25
MIN_SWING_DEG = 25.0
MIN_VISIBILITY = 0.5


def phases_from_angles(raw: np.ndarray, fps: float, down_is_decreasing: bool) -> np.ndarray:
    """판정 신호 시계열 → phase, 극값 전환점마다 0 1 교대, 미검출 -1"""
    n = len(raw)
    detected = ~np.isnan(raw)
    if detected.sum() < 5:
        return np.full(n, -1, dtype=int)

    idx = np.arange(n)
    filled = np.interp(idx, idx[detected], raw[detected])
    win = max(5, int(SMOOTH_SECONDS * fps) | 1)
    smooth = savgol_filter(filled, win, 2)
    if not down_is_decreasing:
        smooth = -smooth

    tops, _ = find_peaks(smooth, prominence=MIN_SWING_DEG)
    bottoms, _ = find_peaks(-smooth, prominence=MIN_SWING_DEG)
    turns = sorted([(i, 0) for i in tops] + [(i, 1) for i in bottoms])
    if not turns:
        return np.full(n, -1, dtype=int)

    phase = np.full(n, 1 - turns[0][1], dtype=int)
    for i, after in turns:
        phase[i:] = after

    gap = int(DETECT_GAP_SECONDS * fps)
    near = np.convolve(detected.astype(int), np.ones(2 * gap + 1), mode="same") > 0
    phase[~near] = -1
    return phase


def row_phases(timestamps: np.ndarray, phase: np.ndarray, fps: float, video_start: float) -> list[int]:
    """IMU 행 timestamp → 프레임 대응, 영상 밖은 -1"""
    out = []
    for t in timestamps:
        fi = int(round((float(t) - video_start) * fps))
        out.append(int(phase[fi]) if 0 <= fi < len(phase) else -1)
    return out


def phase_counts(row_phase: list[int]) -> dict:
    """렙 수, 행 수, phase 별 행 수"""
    values, counts = np.unique(np.array(row_phase, dtype=int), return_counts=True)
    return {
        "repCount": count_reps([p for p in row_phase if p >= 0]),
        "rows": len(row_phase),
        "rowPhaseCounts": {str(int(v)): int(c) for v, c in zip(values, counts)},
    }


def summarize(angles: np.ndarray, fps: float, row_phase: list[int]) -> dict:
    """라벨링 요약, 프레임 수, 검출 비율, phase 행 수"""
    return {
        "frames": int(len(angles)),
        "fps": round(float(fps), 2),
        "videoSeconds": round(len(angles) / fps, 1),
        "detectedFraction": round(float(np.mean(~np.isnan(angles))), 3),
        **phase_counts(row_phase),
    }
