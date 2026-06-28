import torch
import torch.nn as nn


class FitSetModel(nn.Module):
    def __init__(self, num_classes: int):
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
        # x: [B, 200, 6]
        x = x.permute(0, 2, 1)          # [B, 6, 200]
        x = self.conv(x)                 # [B, 256, 100]
        x = x.permute(0, 2, 1)          # [B, 100, 256]
        _, (h, _) = self.lstm(x)        # h: [1, B, 128]
        x = h.squeeze(0)                 # [B, 128]
        return self.fc(x)                # [B, num_classes] — raw logits


class WrappedModel(nn.Module):
    """정규화 + Softmax 내장 모델 — 변환 및 온디바이스 추론용"""
    
    def __init__(self, model: FitSetModel, mean: list[float], std: list[float]):
        super().__init__()
        self.model = model
        self.register_buffer("mean", torch.tensor(mean, dtype=torch.float32))
        self.register_buffer("std", torch.tensor(std, dtype=torch.float32))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: [1, 200, 6] — raw IMU 값
        x = (x - self.mean) / self.std
        logits = self.model(x)
        return torch.softmax(logits, dim=-1)
