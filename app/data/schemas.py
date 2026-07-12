# ─────────────────────────────────────────────────────────────────────────────
# data 도메인 요청/응답 스키마 (Pydantic DTO). ORM이 없으므로 이것이 유일한 모델 정의다.
# ─────────────────────────────────────────────────────────────────────────────
from pydantic import BaseModel


class UploadConfirmRequest(BaseModel):   # POST /data/upload-confirm 바디: {filename, class_name}
    filename: str
    class_name: str   # JSON 키도 그대로 'class_name' (class는 파이썬 예약어라 snake_case 유지)
