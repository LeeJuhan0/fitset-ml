import numpy as np

from app.motions.utils import L, joint_angle

LANDMARKS = (L.HIP, L.SHOULDER, L.ELBOW)
DOWN_IS_DECREASING = False


def signal(world: np.ndarray, image: np.ndarray) -> np.ndarray:
    """왼 어깨 각도, 바 머리 뒤로 내릴 때 증가"""
    return joint_angle(world, L.HIP, L.SHOULDER, L.ELBOW)
