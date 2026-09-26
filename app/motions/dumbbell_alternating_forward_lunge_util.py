import numpy as np

from app.motions.utils import L, joint_angle

LANDMARKS = (L.HIP, L.KNEE, L.ANKLE)
DOWN_IS_DECREASING = True


def signal(world: np.ndarray, image: np.ndarray) -> np.ndarray:
    """왼 무릎 각도, 양쪽 런지 모두 앉을 때 감소"""
    return joint_angle(world, L.HIP, L.KNEE, L.ANKLE)
