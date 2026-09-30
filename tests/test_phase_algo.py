import numpy as np

from app.labeling import algo
from app.phase import algo as phase_algo

FPS = 30.0


def _reps(n=4, period_s=2.0, hold_s=1.5, lo=70.0, hi=170.0):
    hold = np.full(int(hold_s * FPS), hi)
    t = np.linspace(0, 1, int(period_s * FPS), endpoint=False)
    rep = hi - (hi - lo) * (1 - np.cos(2 * np.pi * t)) / 2
    return np.concatenate([hold, np.tile(rep, n), hold])


def _segments(phase):
    out, start = [], 0
    for i in range(1, len(phase) + 1):
        if i < len(phase) and phase[i] == phase[start]:
            continue
        out.append(int(phase[start]))
        start = i
    return out


def test_pushup_only_down_up_switching_at_turns():
    angles = _reps()
    phase = algo.phases_from_angles(angles, FPS, down_is_decreasing=True)
    assert set(phase.tolist()) == {0, 1}
    assert _segments(phase) == [0, 1] * 4
    bottom = int(1.5 * FPS + FPS)
    assert phase[bottom - 3] == 0 and phase[bottom + 3] == 1


def test_curl_direction_is_inverted():
    phase = algo.phases_from_angles(_reps(), FPS, down_is_decreasing=False)
    assert _segments(phase)[:2] == [1, 0]


def test_small_swing_and_undetected_is_minus_one():
    phase = algo.phases_from_angles(_reps(n=1, lo=160.0), FPS, True)
    assert (phase == -1).all()

    angles = _reps()
    angles[:60] = np.nan
    phase = algo.phases_from_angles(angles, FPS, True)
    assert (phase[:50] == -1).all()
    assert (phase[70:] != -1).all()

    assert (algo.phases_from_angles(np.full(100, np.nan), FPS, True) == -1).all()


def test_row_phases_map_rows_to_frames_and_summarize():
    phase = np.array([1, 1, 0, 0, 1, 1], dtype=int)
    video_start = 1000.0
    ts = np.array([video_start + i / FPS for i in range(6)] + [video_start + 5.0])
    row_phase = algo.row_phases(ts, phase, FPS, video_start)
    assert row_phase == [1, 1, 0, 0, 1, 1, -1]

    summary = algo.summarize(np.array([100.0, np.nan, 120.0, 130.0]), FPS, row_phase)
    assert summary["frames"] == 4 and summary["detectedFraction"] == 0.75
    assert summary["rowPhaseCounts"] == {"-1": 1, "0": 2, "1": 4}
    assert summary["repCount"] == 1


def test_windows_majority_and_rep_count():
    x = np.zeros((20, 6), dtype=np.float32)
    y = np.array([0] * 5 + [1] * 5 + [-1] * 5 + [2] * 5)
    xs, ys = phase_algo.make_windows(x, y, window=5, stride=5)
    assert xs.shape == (2, 5, 6) and ys.tolist() == [0, 1]
    assert phase_algo.window_label(np.array([0, 0, -1, -1, -1, -1])) == -1
    assert phase_algo.window_label(np.array([0, 0, 1, 1, 1])) == 1
    assert phase_algo.count_reps([1, 0, 0, 1, 1, 0, 1, 0]) == 3
    assert phase_algo.count_reps([0, 0, 0]) == 0

