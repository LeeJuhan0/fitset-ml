import numpy as np

from app.motions.utils import ARMS, both_elbows

LANDMARKS = ARMS
DOWN_IS_DECREASING = False


def signal(world: np.ndarray, image: np.ndarray) -> np.ndarray:
    """양 팔꿈치 평균, 밀어 내릴 때 증가"""
    return both_elbows(world)
