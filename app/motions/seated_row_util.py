import numpy as np

from app.motions.utils import ARMS, both_elbows

LANDMARKS = ARMS
DOWN_IS_DECREASING = False


def signal(world: np.ndarray, image: np.ndarray) -> np.ndarray:
    """양 팔꿈치 평균, 팔 펴 돌아갈 때 증가"""
    return both_elbows(world)
