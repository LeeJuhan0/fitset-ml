def timestamp_scale(dt_median: float) -> float:
    """타임스탬프 1초당 단위 수, 샘플 간격 중앙값으로 ns ms s 판별"""
    if dt_median > 1e5:
        return 1e9
    if dt_median > 1:
        return 1e3
    return 1.0
