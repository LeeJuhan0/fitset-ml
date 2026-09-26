import numpy as np

from app.motions.utils import L, R, arm_opening

LANDMARKS = (L.SHOULDER, R.SHOULDER, L.ELBOW)
DOWN_IS_DECREASING = True


def signal(world: np.ndarray, image: np.ndarray) -> np.ndarray:
    """왼팔 벌림 각도, 팔 내릴 때 감소"""
    return arm_opening(world)
