import numpy as np

from app.motions.utils import L, joint_angle

LANDMARKS = (L.SHOULDER, L.HIP, L.KNEE)
DOWN_IS_DECREASING = True


def signal(world: np.ndarray, image: np.ndarray) -> np.ndarray:
    """왼 엉덩이 각도 영상 평면, 상체 말아 숙일 때 감소"""
    return joint_angle(image, L.SHOULDER, L.HIP, L.KNEE)
