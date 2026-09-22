import numpy as np
import pandas as pd

WINDOW = 200
STRIDE = 100
TRIM_SAMPLES = 300
CHANNELS = ["ax", "ay", "az", "gx", "gy", "gz"]


def load_table(path: str) -> pd.DataFrame:
    """확장자별 로드, parquet 또는 csv, 헤더 공백 제거"""
    if path.endswith(".parquet"):
        df = pd.read_parquet(path)
    if not path.endswith(".parquet"):
        df = pd.read_csv(path)
    df.columns = df.columns.str.strip()
    return df


def load_csv(path: str) -> tuple[np.ndarray, np.ndarray]:
    """CSV·parquet 로드, 신호와 라벨 배열"""
    df = load_table(path)
    signals = df[CHANNELS].values.astype(np.float32)
    labels = df["label"].values

    if len(signals) - 2 * TRIM_SAMPLES >= WINDOW:
        signals = signals[TRIM_SAMPLES:-TRIM_SAMPLES]
        labels = labels[TRIM_SAMPLES:-TRIM_SAMPLES]
    return signals, labels


def sliding_window(
    signals: np.ndarray,
    labels: np.ndarray,
    classes: list[str],
    window: int = WINDOW,
    stride: int = STRIDE,
    offset: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """슬라이딩 윈도우 세그먼테이션 → (windows [M, W, 6], label_ids [M])"""
    xs, ys = [], []
    n = len(signals)
    for start in range(offset, n - window + 1, stride):
        seg = signals[start : start + window]
        seg_labels = labels[start : start + window]
        vals, counts = np.unique(seg_labels, return_counts=True)
        majority = vals[counts.argmax()]
        if majority not in classes:
            continue
        xs.append(seg)
        ys.append(classes.index(majority))
    return np.array(xs, dtype=np.float32), np.array(ys, dtype=np.int64)


def compute_stats(windows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """채널별 mean·std 계산 — WrappedModel 정규화에 사용"""
    flat = windows.reshape(-1, windows.shape[-1])
    return flat.mean(axis=0).tolist(), flat.std(axis=0).tolist()


def normalize(windows: np.ndarray, mean: list, std: list) -> np.ndarray:
    """채널별 mean std 정규화"""
    return ((windows - np.array(mean, dtype=np.float32)) / (np.array(std, dtype=np.float32) + 1e-8)).astype(np.float32)
