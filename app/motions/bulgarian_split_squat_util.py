import numpy as np

from app.motions.utils import L, joint_angle

LANDMARKS = (L.HIP, L.KNEE, L.ANKLE)
DOWN_IS_DECREASING = True


def signal(world: np.ndarray, image: np.ndarray) -> np.ndarray:
    """왼 앞다리 무릎 각도 영상 평면, 앉을 때 감소"""
    return joint_angle(image, L.HIP, L.KNEE, L.ANKLE)
