import numpy as np

from scipy.signal import medfilt, savgol_filter

from app.phase.algo import count_reps

SMOOTH_SECONDS = 0.3
PAUSE_DEG_PER_S = 20.0
MIN_SEGMENT_SECONDS = 0.15
DETECT_GAP_SECONDS = 0.25
MIN_PAUSE_SECONDS = 0.4
MIN_SWING_DEG = 25.0
MIN_VISIBILITY = 0.5


def phases_from_angles(raw: np.ndarray, fps: float, down_is_decreasing: bool) -> np.ndarray:
    """판정 신호 시계열 → phase, 스무딩, 속도, 멈춤, 미검출 -1"""
    n = len(raw)
    detected = ~np.isnan(raw)
    if detected.sum() < 5:
        return np.full(n, -1, dtype=int)

    idx = np.arange(n)
    filled = np.interp(idx, idx[detected], raw[detected])
    win = max(5, int(SMOOTH_SECONDS * fps) | 1)
    smooth = savgol_filter(filled, win, 2)
    vel = savgol_filter(filled, win, 2, deriv=1, delta=1.0 / fps)
    if not down_is_decreasing:
        vel = -vel

    phase = np.where(np.abs(vel) < PAUSE_DEG_PER_S, 2, np.where(vel < 0, 0, 1))
    phase = medfilt(phase, max(3, int(0.2 * fps) | 1)).astype(int)
    phase = absorb_short_segments(phase, int(MIN_SEGMENT_SECONDS * fps))
    phase = drop_small_swings(phase, smooth, MIN_SWING_DEG)
    phase = absorb_short_segments(phase, int(MIN_SEGMENT_SECONDS * fps))
    phase = split_short_pauses(phase, int(MIN_PAUSE_SECONDS * fps))

    gap = int(DETECT_GAP_SECONDS * fps)
    near = np.convolve(detected.astype(int), np.ones(2 * gap + 1), mode="same") > 0
    phase[~near] = -1
    return phase


def drop_small_swings(phase: np.ndarray, angle_deg: np.ndarray, min_swing: float) -> np.ndarray:
    """각도 변화 작은 0 1 구간 → 멈춤 2"""
    out = phase.copy()
    start = 0
    for i in range(1, len(out) + 1):
        if i < len(out) and out[i] == out[start]:
            continue
        if out[start] in (0, 1) and abs(angle_deg[i - 1] - angle_deg[start]) < min_swing:
            out[start:i] = 2
        start = i
    return out


def split_short_pauses(phase: np.ndarray, min_len: int) -> np.ndarray:
    """짧은 멈춤 분할, 앞뒤 동작에 흡수"""
    out = phase.copy()
    start = 0
    for i in range(1, len(out) + 1):
        if i < len(out) and out[i] == out[start]:
            continue
        if out[start] == 2 and i - start < min_len and start > 0 and i < len(out):
            mid = (start + i) // 2
            out[start:mid] = out[start - 1]
            out[mid:i] = out[i]
        start = i
    return out


def absorb_short_segments(phase: np.ndarray, min_len: int) -> np.ndarray:
    """짧은 구간 앞 구간에 흡수"""
    out = phase.copy()
    start = 0
    for i in range(1, len(out) + 1):
        if i < len(out) and out[i] == out[start]:
            continue
        if i - start < min_len and start > 0:
            out[start:i] = out[start - 1]
        start = i
    return out


def row_phases(timestamps: np.ndarray, phase: np.ndarray, fps: float, video_start: float) -> list[int]:
    """IMU 행 timestamp → 프레임 대응, 영상 밖은 -1"""
    out = []
    for t in timestamps:
        fi = int(round((float(t) - video_start) * fps))
        out.append(int(phase[fi]) if 0 <= fi < len(phase) else -1)
    return out


def summarize(angles: np.ndarray, fps: float, row_phase: list[int]) -> dict:
    """라벨링 요약, 프레임 수, 검출 비율, phase 행 수"""
    values, counts = np.unique(np.array(row_phase, dtype=int), return_counts=True)
    return {
        "repCount": count_reps([p for p in row_phase if p >= 0]),
        "frames": int(len(angles)),
        "fps": round(float(fps), 2),
        "videoSeconds": round(len(angles) / fps, 1),
        "detectedFraction": round(float(np.mean(~np.isnan(angles))), 3),
        "rows": len(row_phase),
        "rowPhaseCounts": {str(int(v)): int(c) for v, c in zip(values, counts)},
    }
