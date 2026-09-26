import numpy as np

from app.motions.utils import TORSO, torso_lean

LANDMARKS = TORSO
DOWN_IS_DECREASING = False


def signal(world: np.ndarray, image: np.ndarray) -> np.ndarray:
    """몸통 기울기, 숙여 내릴 때 증가"""
    return torso_lean(world)
