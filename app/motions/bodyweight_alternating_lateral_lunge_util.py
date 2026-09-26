import numpy as np

from app.motions.utils import LEGS, both_knees

LANDMARKS = LEGS
DOWN_IS_DECREASING = True


def signal(world: np.ndarray, image: np.ndarray) -> np.ndarray:
    """양 무릎 평균, 옆으로 앉을 때 감소"""
    return both_knees(world)
