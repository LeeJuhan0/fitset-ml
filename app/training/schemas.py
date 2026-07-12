# ─────────────────────────────────────────────────────────────────────────────
# training 도메인 요청 스키마 (Pydantic DTO).
# ─────────────────────────────────────────────────────────────────────────────
from pydantic import BaseModel


class TrainRequest(BaseModel):   # POST /train 바디 스키마
    files: list[str]             # 학습에 쓸 파일명 목록(필수)
    epochs: int = 200            # 에폭 수(기본 200)
    lr: float = 0.001            # 학습률(기본 0.001)
