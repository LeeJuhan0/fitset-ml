import numpy as np

from app.motions.utils import L, joint_angle

LANDMARKS = (L.SHOULDER, L.ELBOW, L.WRIST)
DOWN_IS_DECREASING = False


def signal(world: np.ndarray, image: np.ndarray) -> np.ndarray:
    """왼 팔꿈치 각도, 덤벨 내릴 때 증가"""
    return joint_angle(world, L.SHOULDER, L.ELBOW, L.WRIST)
