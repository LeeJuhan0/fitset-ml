from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경변수·.env 로 덮어쓰는 설정"""
    model_config = SettingsConfigDict(env_file=".env")

    mlflow_tracking_uri: str = "http://localhost:5001/mlflow"
    mlflow_proxy_target: str = "http://localhost:5001"
    mlflow_ui_user: str = ""
    mlflow_ui_password: str = ""

    raw_data_bucket: str = "fitset-dataset"
    models_bucket: str = "fitset-models"
    collect_imu_bucket: str = "fitset-collect-imu"
    collect_video_bucket: str = "fitset-collect-video"
    collect_labeled_bucket: str = "fitset-collect-labeled"
    phase_models_bucket: str = "fitset-phase-models"
    aws_region: str = "ap-northeast-2"

    database_url: str = "sqlite+aiosqlite:///./fitset_ml.db"
    pose_model_path: str = "models/pose_landmarker_full.task"
    class_mapping_url: str = "https://d31w3ih1t93w7x.cloudfront.net/models/class-mapping.json"


settings = Settings()

PLATFORMS = {"ios", "android"}

CLASSES = [
    "SQUAT",
    "PUSHUP",
    "DUMBBELL_CURL",
    "SIDE_LATERAL_RAISE",
    "REST",
    "OVERHEAD_PRESS",
    "BARBELL_ROW",
    "DEADLIFT",
    "LAT_PULLDOWN",
    "BENCH_PRESS",
    "PEC_DECK_FLY",
    "HIP_THRUST",
    "SEATED_ROW",
    "DIPS",
]

PHASE_CLASSES = ["SQUAT", "PUSHUP", "DUMBBELL_CURL"]
