from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # MLflow — ADR-0017: EC2 온디맨드 + EBS SQLite
    # EC2에서 MLflow 서버가 sqlite:////mlflow/mlflow.db 로 뜨면 이 URI를 사용
    mlflow_tracking_uri: str = "http://localhost:5001"
    mlflow_artifact_root: str = "s3://fitset-models/mlflow"

    # S3 버킷 — ADR-0015: raw data / model artifact 분리
    raw_data_bucket: str = "fitset-dataset"
    models_bucket: str = "fitset-models"

    # AWS
    aws_region: str = "ap-northeast-2"

    class Config:
        env_file = ".env"


settings = Settings()

PLATFORMS = {"ios", "android"}
CLASSES = ["SQUAT", "PUSHUP", "DUMBBELL_CURL", "SIDE_LATERAL_RAISE", "REST"]
