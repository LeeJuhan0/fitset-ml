from app.core.schemas import CamelModel


class ImuResponse(CamelModel):
    """imu 응답, 시작 기준 초, 채널별 값"""
    filename: str
    t: list[float]
    channels: dict[str, list[float]]
