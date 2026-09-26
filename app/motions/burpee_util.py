import numpy as np

from app.motions.utils import NOSE, L, R, height

LANDMARKS = (NOSE, L.HIP, L.ANKLE, R.ANKLE)
DOWN_IS_DECREASING = True


def signal(world: np.ndarray, image: np.ndarray) -> np.ndarray:
    """왼 엉덩이 높이, 바닥으로 내려갈 때 감소"""
    return height(image, L.HIP)
