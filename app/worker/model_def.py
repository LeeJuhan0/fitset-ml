import torch
import torch.nn as nn


class FitSetModel(nn.Module):
    """CNN-LSTM 분류 모델, 6채널 입력"""
    def __init__(self, num_classes: int):
        """상태코드와 detail 고정"""
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv1d(6, 256, kernel_size=5, stride=1, padding=2),
            nn.BatchNorm1d(256),
            nn.ReLU(),
            nn.MaxPool1d(2),
            nn.Dropout(0.25),
        )
        self.lstm = nn.LSTM(256, 128, batch_first=True)
        self.fc = nn.Sequential(
            nn.Linear(128, 128),
            nn.ReLU(),
            nn.Linear(128, num_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """순전파, logits 또는 확률"""
        x = x.permute(0, 2, 1)
        x = self.conv(x)
        x = x.permute(0, 2, 1)
        _, (h, _) = self.lstm(x)
        x = h.squeeze(0)
        return self.fc(x)


class WrappedModel(nn.Module):
    """정규화 + Softmax 내장 모델 — 변환 및 온디바이스 추론용"""

    def __init__(self, model: FitSetModel, mean: list[float], std: list[float]):
        """상태코드와 detail 고정"""
        super().__init__()
        self.model = model
        self.register_buffer("mean", torch.tensor(mean, dtype=torch.float32))
        self.register_buffer("std", torch.tensor(std, dtype=torch.float32))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """순전파, logits 또는 확률"""
        x = (x - self.mean) / self.std
        logits = self.model(x)
        return torch.softmax(logits, dim=-1)
