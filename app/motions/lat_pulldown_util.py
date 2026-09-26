import numpy as np

from app.motions.utils import L, joint_angle

LANDMARKS = (L.SHOULDER, L.ELBOW, L.WRIST)
DOWN_IS_DECREASING = True


def signal(world: np.ndarray, image: np.ndarray) -> np.ndarray:
    """왼 팔꿈치 각도, 바 당겨 내릴 때 감소"""
    return joint_angle(world, L.SHOULDER, L.ELBOW, L.WRIST)
