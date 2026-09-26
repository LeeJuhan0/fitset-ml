import numpy as np

from app.motions.utils import ARMS, both_arm_opening

LANDMARKS = ARMS
DOWN_IS_DECREASING = False


def signal(world: np.ndarray, image: np.ndarray) -> np.ndarray:
    """양팔 벌림 각도, 팔 벌려 내릴 때 증가"""
    return both_arm_opening(world)
