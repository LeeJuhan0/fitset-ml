import numpy as np

from app.motions.utils import TORSO, torso_twist

LANDMARKS = TORSO
DOWN_IS_DECREASING = False


def signal(world: np.ndarray, image: np.ndarray) -> np.ndarray:
    """몸통 회전각, 왼쪽 케이블로 돌아갈 때 증가"""
    return torso_twist(world)
