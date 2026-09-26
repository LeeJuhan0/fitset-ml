import numpy as np

from app.motions.utils import ARMS, both_elbows

LANDMARKS = ARMS
DOWN_IS_DECREASING = True


def signal(world: np.ndarray, image: np.ndarray) -> np.ndarray:
    """양 팔꿈치 평균, 손잡이 돌아올 때 감소"""
    return both_elbows(world)
