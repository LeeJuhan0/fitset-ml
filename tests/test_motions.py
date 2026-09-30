import pathlib

import numpy as np
import pytest

from app.motions.utils import L, R, joint_angle, load_motion, torso_lean, torso_twist
from app.labeling.worker import motion_signal

CLASSES = sorted(p.name[:-len("_util.py")].upper() for p in pathlib.Path("app/motions").glob("*_util.py"))


def _pose(n=40, seed=0):
    return np.random.default_rng(seed).normal(size=(n, 33, 3))


def test_forty_five_motions_expose_signal_and_direction():
    assert len(CLASSES) == 45
    for class_name in CLASSES:
        motion = load_motion(class_name)
        assert isinstance(motion.DOWN_IS_DECREASING, bool)
        assert all(0 <= j < 33 for j in motion.LANDMARKS)
        out = motion.signal(_pose(), _pose(seed=1))
        assert out.shape == (40,) and np.isfinite(out).all(), class_name


def test_unknown_class_has_no_motion():
    assert load_motion("WALL_SIT") is None
    assert load_motion("SQUAT").DOWN_IS_DECREASING is True
    assert load_motion("DUMBBELL_CURL").DOWN_IS_DECREASING is False


def test_joint_angle_lean_and_twist_geometry():
    p = np.zeros((1, 33, 3))
    p[0, L.SHOULDER], p[0, L.WRIST] = [1, 0, 0], [0, 1, 0]
    assert round(joint_angle(p, L.SHOULDER, L.ELBOW, L.WRIST)[0]) == 90
    p[0, L.WRIST] = [-1, 0, 0]
    assert round(joint_angle(p, L.SHOULDER, L.ELBOW, L.WRIST)[0]) == 180

    t = np.zeros((1, 33, 3))
    t[0, L.HIP], t[0, R.HIP] = [0.1, 0, 0], [-0.1, 0, 0]
    t[0, L.SHOULDER], t[0, R.SHOULDER] = [0.1, -0.5, 0], [-0.1, -0.5, 0]
    assert round(torso_lean(t)[0]) == 0 and round(torso_twist(t)[0]) == 0
    t[0, L.SHOULDER, 1] = t[0, R.SHOULDER, 1] = 0.0
    t[0, L.SHOULDER, 2] = t[0, R.SHOULDER, 2] = 0.5
    assert round(torso_lean(t)[0]) == 90


def test_motion_signal_masks_low_visibility_and_missing_motion():
    motion = load_motion("SQUAT")
    vis = np.ones((40, 33))
    vis[:10, [L.HIP, L.KNEE, L.ANKLE]] = 0.0
    out = motion_signal(motion, _pose(), _pose(seed=1), vis)
    assert np.isnan(out[:10]).all() and np.isfinite(out[10:]).all()
    assert np.isnan(motion_signal(None, _pose(), _pose(), vis)).all()


@pytest.mark.parametrize("class_name", ["SQUAT", "PUSHUP"])
def test_rep_signal_labels_peaks(class_name):
    from app.labeling import algo
    from app.phase.algo import count_reps
    fps = 30.0
    t = np.linspace(0, 1, 60, endpoint=False)
    angle = np.concatenate([np.full(45, 170.0), np.tile(170 - 100 * (1 - np.cos(2 * np.pi * t)) / 2, 3), np.full(45, 170.0)])
    phase = algo.phases_from_angles(angle, fps, load_motion(class_name).DOWN_IS_DECREASING)
    moves = [k for k in phase if k in (0, 1)]
    assert moves[0] == 1 and count_reps(phase.tolist()) == 3
