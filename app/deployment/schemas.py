# ─────────────────────────────────────────────────────────────────────────────
# deployment 도메인 요청 스키마 (Pydantic DTO).
# ─────────────────────────────────────────────────────────────────────────────
from pydantic import BaseModel


class DeployRequest(BaseModel):   # POST /deploy 바디
    version: str                  # 배포할 버전(예: v1.3)
