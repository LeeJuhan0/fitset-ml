import numpy as np

from app.motions.utils import L, joint_angle

LANDMARKS = (L.SHOULDER, L.ELBOW, L.WRIST)
DOWN_IS_DECREASING = False


def signal(world: np.ndarray, image: np.ndarray) -> np.ndarray:
    """왼 팔꿈치 각도, 팔 펴 돌아갈 때 증가"""
    return joint_angle(world, L.SHOULDER, L.ELBOW, L.WRIST)
