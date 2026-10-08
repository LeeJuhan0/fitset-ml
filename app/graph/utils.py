import numpy as np


def timestamp_scale(dt_median: float) -> float:
    """타임스탬프 1초당 단위 수, 샘플 간격 중앙값으로 ns ms s 판별"""
    if dt_median > 1e5:
        return 1e9
    if dt_median > 1:
        return 1e3
    return 1.0


def acc_pc1(acc: np.ndarray) -> tuple[np.ndarray, float] | None:
    """가속도 3축 제1주성분 사영과 설명 분산 비율, 2행 미만이나 NaN 이면 None"""
    from sklearn.decomposition import PCA

    if len(acc) < 2 or not np.isfinite(acc).all():
        return None
    pca = PCA(n_components=1)
    return pca.fit_transform(acc)[:, 0], float(pca.explained_variance_ratio_[0])
