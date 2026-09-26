import numpy as np

from app.motions.utils import L, joint_angle

LANDMARKS = (L.SHOULDER, L.HIP, L.KNEE)
DOWN_IS_DECREASING = False


def signal(world: np.ndarray, image: np.ndarray) -> np.ndarray:
    """왼 엉덩이 각도, 상체 눕힐 때 증가"""
    return joint_angle(world, L.SHOULDER, L.HIP, L.KNEE)
