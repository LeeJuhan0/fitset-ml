import numpy as np

from app.motions.utils import NOSE, L, R, height

LANDMARKS = (NOSE, L.WRIST, L.ANKLE, R.ANKLE)
DOWN_IS_DECREASING = True


def signal(world: np.ndarray, image: np.ndarray) -> np.ndarray:
    """왼 손목 높이, 바 내릴 때 감소"""
    return height(image, L.WRIST)
