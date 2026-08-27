# ─────────────────────────────────────────────────────────────────────────────
# 전처리 — trainer.py가 학습 직전에 CSV를 모델 입력 형태로 가공할 때 쓴다.
# numpy: 수치 배열 연산,  pandas: CSV 읽기/표 처리.
# ─────────────────────────────────────────────────────────────────────────────
import numpy as np
import pandas as pd

WINDOW = 200   # 2초 × 100Hz  — 한 윈도우(=모델 입력 1개)의 샘플 수
STRIDE = 100   # 1초 stride    — 윈도우를 100샘플씩 밀며 자른다(50% overlap)
TRIM_SAMPLES = 300   # 3초 × 100Hz — 파일 앞뒤로 버리는 샘플 수(기기 조작·자세 잡기 노이즈 구간)
CHANNELS = ["ax", "ay", "az", "gx", "gy", "gz"]   # CSV에서 읽을 6개 IMU 열(가속도 xyz + 자이로 xyz)


def load_csv(path: str) -> tuple[np.ndarray, np.ndarray]:
    """CSV 로드 → (signals [N, 6], labels [N]) 반환"""
    # path: 로컬 CSV 파일 경로(S3에서 받아둔 임시 파일). 반환: 신호배열과 행별 라벨.
    df = pd.read_csv(path)                              # CSV → DataFrame
    df.columns = df.columns.str.strip()                # 헤더 공백 제거(" ax" → "ax")
    signals = df[CHANNELS].values.astype(np.float32)   # 6개 채널 열만 뽑아 [N,6] float32 배열
    labels = df["label"].values                        # 행별 라벨(문자열 종목명) [N]

    # 앞뒤 3초(TRIM_SAMPLES)를 버림 — 시작·종료 시점의 비운동 노이즈 제거.
    # 잘라도 윈도우 1개(WINDOW)가 안 나올 만큼 짧은 파일은 자르지 않고 그대로 둔다.
    if len(signals) - 2 * TRIM_SAMPLES >= WINDOW:
        signals = signals[TRIM_SAMPLES:-TRIM_SAMPLES]
        labels = labels[TRIM_SAMPLES:-TRIM_SAMPLES]
    return signals, labels


def sliding_window(
    signals: np.ndarray,    # [N, 6] 원신호
    labels: np.ndarray,     # [N]   행별 라벨
    classes: list[str],     # 라벨 문자열 → 인덱스 변환표(CLASSES)
    window: int = WINDOW,   # 윈도우 길이(기본 200)
    stride: int = STRIDE,   # 이동 간격(기본 100)
    offset: int = 0,        # 시작점 이동(증강용)
) -> tuple[np.ndarray, np.ndarray]:
    """슬라이딩 윈도우 세그먼테이션 → (windows [M, W, 6], label_ids [M])

    offset: 시작점을 [0, stride) 만큼 밀어 윈도우의 위상(phase)을 바꾼다.
            학습 시 에폭마다 랜덤 오프셋을 주면 임의 시작점(추론)에 강건해진다(증강).
            기본 0 → 기존 동작과 동일(추론·평가는 0 고정).
    """
    xs, ys = [], []
    n = len(signals)
    # offset부터 시작해 stride 간격으로 window 크기만큼 잘라 나간다.
    for start in range(offset, n - window + 1, stride):
        seg = signals[start : start + window]          # [W, 6] 한 조각
        seg_labels = labels[start : start + window]    # 그 조각의 라벨들
        # 윈도우 내 다수결 라벨 (모두 같은 라벨이면 그대로)
        vals, counts = np.unique(seg_labels, return_counts=True)   # 등장 라벨과 횟수
        majority = vals[counts.argmax()]                           # 가장 많은 라벨 = 이 윈도우의 정답
        if majority not in classes:                                # 정의된 종목이 아니면 버림
            continue
        xs.append(seg)
        ys.append(classes.index(majority))            # 라벨 문자열 → 클래스 번호(int)
    return np.array(xs, dtype=np.float32), np.array(ys, dtype=np.int64)


def compute_stats(windows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """채널별 mean·std 계산 — WrappedModel 정규화에 사용"""
    # windows: [M, W, 6]. 채널(마지막 축) 기준 통계만 필요하므로 [전체샘플, 6]으로 펴서 계산.
    flat = windows.reshape(-1, windows.shape[-1])      # [M*W, 6]
    return flat.mean(axis=0).tolist(), flat.std(axis=0).tolist()   # 각 6개 값(list) 반환


def normalize(windows: np.ndarray, mean: list, std: list) -> np.ndarray:
    # (x-mean)/std. +1e-8은 std=0일 때 0으로 나누는 것 방지.
    return ((windows - np.array(mean, dtype=np.float32)) / (np.array(std, dtype=np.float32) + 1e-8)).astype(np.float32)
