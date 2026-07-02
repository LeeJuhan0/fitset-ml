# ─────────────────────────────────────────────────────────────────────────────
# 모델 정의. trainer.py(학습)와 convert.py(변환)가 이 두 클래스를 가져다 쓴다.
# nn.Module: 모든 PyTorch 모델/레이어의 부모 클래스. forward()를 정의하면 model(x)로 호출된다.
# ─────────────────────────────────────────────────────────────────────────────
import torch
import torch.nn as nn   # nn: 레이어(Conv1d/LSTM/Linear...)와 손실함수가 든 모듈


class FitSetModel(nn.Module):
    # 운동 종목 분류기(CNN-LSTM). trainer.py에서 FitSetModel(num_classes=len(CLASSES))로 생성.
    def __init__(self, num_classes: int):
        # num_classes: 출력 종목 수(=len(CLASSES)=5). 마지막 Linear의 출력 차원을 결정.
        super().__init__()
        # nn.Sequential : 여러 레이어를 순서대로 통과시키는 컨테이너.
        self.conv = nn.Sequential(
            nn.Conv1d(6, 256, kernel_size=5, stride=1, padding=2),  # 입력 6채널→256채널, 시간축 1D 합성곱
            nn.BatchNorm1d(256),   # 채널별 정규화(학습 안정화)
            nn.ReLU(),             # 비선형 활성(음수→0)
            nn.MaxPool1d(2),       # 시간축 길이 1/2 다운샘플(200→100)
            nn.Dropout(0.25),      # 학습 시 25% 뉴런 임의 차단(과적합 완화)
        )
        # nn.LSTM(input_size=256, hidden_size=128, batch_first=True)
        #   batch_first=True → 입력 형태가 [Batch, Time, Feature]. 시계열의 시간 흐름을 요약.
        self.lstm = nn.LSTM(256, 128, batch_first=True)
        self.fc = nn.Sequential(
            nn.Linear(128, 128),   # 완전연결 128→128
            nn.ReLU(),
            nn.Linear(128, num_classes),   # 128→종목 수. 최종 점수(logits) 출력
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: [B, 200, 6]  (B=배치, 200=2초 윈도우 샘플, 6=IMU 채널)
        x = x.permute(0, 2, 1)          # [B, 6, 200] — Conv1d는 [B, 채널, 길이] 형태를 요구
        x = self.conv(x)                 # [B, 256, 100]
        x = x.permute(0, 2, 1)          # [B, 100, 256] — LSTM은 [B, 시간, 특징] (batch_first)
        _, (h, _) = self.lstm(x)        # LSTM 반환 (출력시퀀스, (h_n, c_n)). h_n: 마지막 hidden [1, B, 128]
        x = h.squeeze(0)                 # [B, 128] — 길이 1 차원 제거
        return self.fc(x)                # [B, num_classes] — raw logits (softmax 전)


class WrappedModel(nn.Module):
    """정규화 + Softmax 내장 모델 — 변환 및 온디바이스 추론용"""
    # convert.py가 export 직전에 FitSetModel을 이걸로 감싼다 → 앱은 raw IMU만 넣으면 확률이 나온다.

    def __init__(self, model: FitSetModel, mean: list[float], std: list[float]):
        # model: 학습 끝난 FitSetModel,  mean/std: 학습 train셋에서 구한 채널별 정규화 통계(6개씩)
        super().__init__()
        self.model = model
        # register_buffer: 학습되지 않지만 모델과 함께 저장/이동되는 텐서(가중치 아님). 변환 시 그래프에 박힘.
        self.register_buffer("mean", torch.tensor(mean, dtype=torch.float32))
        self.register_buffer("std", torch.tensor(std, dtype=torch.float32))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: [1, 200, 6] — raw IMU 값 (앱이 센서에서 받은 그대로)
        x = (x - self.mean) / self.std   # 학습과 동일 정규화를 모델 내부에서 수행
        logits = self.model(x)           # FitSetModel 통과 → logits
        return torch.softmax(logits, dim=-1)   # 확률(합=1)로 변환해 반환
