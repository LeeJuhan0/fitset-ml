import numpy as np

from app.motions.utils import L, joint_angle

LANDMARKS = (L.HIP, L.SHOULDER, L.ELBOW)
DOWN_IS_DECREASING = True


def signal(world: np.ndarray, image: np.ndarray) -> np.ndarray:
    """왼 어깨 각도, 바 내릴 때 감소"""
    return joint_angle(world, L.HIP, L.SHOULDER, L.ELBOW)
