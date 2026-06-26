import numpy as np
import pandas as pd

WINDOW = 200   # 2초 × 100Hz
STRIDE = 100   # 1초 stride
CHANNELS = ["ax", "ay", "az", "gx", "gy", "gz"]


def load_csv(path: str) -> tuple[np.ndarray, np.ndarray]:
    """CSV 로드 → (signals [N, 6], labels [N]) 반환"""
    df = pd.read_csv(path)
    df.columns = df.columns.str.strip()
    signals = df[CHANNELS].values.astype(np.float32)
    labels = df["label"].values
    return signals, labels


def sliding_window(
    signals: np.ndarray,
    labels: np.ndarray,
    classes: list[str],
    window: int = WINDOW,
    stride: int = STRIDE,
) -> tuple[np.ndarray, np.ndarray]:
    """슬라이딩 윈도우 세그먼테이션 → (windows [M, W, 6], label_ids [M])"""
    xs, ys = [], []
    n = len(signals)
    for start in range(0, n - window + 1, stride):
        seg = signals[start : start + window]
        seg_labels = labels[start : start + window]
        # 윈도우 내 다수결 라벨 (모두 같은 라벨이면 그대로)
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
    return ((windows - np.array(mean, dtype=np.float32)) / (np.array(std, dtype=np.float32) + 1e-8)).astype(np.float32)
