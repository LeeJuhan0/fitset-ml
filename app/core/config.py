# ─────────────────────────────────────────────────────────────────────────────
# 전역 설정 + 상수. web·worker 양쪽이 공유(core 레이어).
# ─────────────────────────────────────────────────────────────────────────────
from pydantic_settings import BaseSettings   # BaseSettings: 필드를 .env/환경변수로 자동 오버라이드하는 설정 클래스


class Settings(BaseSettings):
    # 아래 각 필드는 "기본값"이며, 같은 이름의 환경변수(.env)가 있으면 그 값으로 대체된다.
    # MLflow — ADR-0017: EC2 온디맨드 + EBS SQLite
    # EC2에서 MLflow 서버가 sqlite:////mlflow/mlflow.db 로 뜨면 이 URI를 사용
    mlflow_tracking_uri: str = "http://localhost:5001"        # MlflowClient/start_run이 접속할 추적 서버 주소
    mlflow_artifact_root: str = "s3://fitset-models/mlflow"   # log_model 등 아티팩트가 저장될 루트(S3)

    # S3 버킷 — ADR-0015: raw data / model artifact 분리
    raw_data_bucket: str = "fitset-dataset"    # 수집 CSV·index.json 이 들어가는 버킷
    models_bucket: str = "fitset-models"       # 모델 산출물·latest.json 이 들어가는 버킷

    # AWS
    aws_region: str = "ap-northeast-2"         # boto3 클라이언트 region

    # 클래스 번호와 운동 slug 매핑 테이블(공개 CDN, GET /model/latest 의 metaUrl 로 내려감)
    class_mapping_url: str = "https://dtcevtkuvdwt9.cloudfront.net/models/class-mapping.json"

    class Config:
        env_file = ".env"                      # 오버라이드 값을 읽어올 파일 경로


settings = Settings()   # 앱 전역에서 import해 쓰는 단일 설정 인스턴스(import settings)

PLATFORMS = {"ios", "android"}   # validate_platform이 허용 여부 검사에 사용하는 집합
# CLASSES: 분류 종목(라벨). 인덱스 = 모델 출력 클래스 번호. 순서가 곧 라벨 id이므로 바꾸면 모델과 어긋난다.
# 새 종목은 반드시 리스트 "끝에" 추가할 것 — 기존 인덱스(0~4)가 밀리면 배포된 모델과 어긋난다.
CLASSES = [
    "SQUAT",
    "PUSHUP",
    "DUMBBELL_CURL",
    "SIDE_LATERAL_RAISE",
    "REST",
    "OVERHEAD_PRESS",      # 오버헤드 프레스
    "BARBELL_ROW",         # 바벨 로우
    "DEADLIFT",            # 데드리프트
    "LAT_PULLDOWN",        # 랫풀다운
    "BENCH_PRESS",         # 벤치 프레스
    "PEC_DECK_FLY",        # 펙덱 플라이 머신
    "HIP_THRUST",          # 힙 쓰러스트
    "SEATED_ROW",          # 시티드 로우
    "DIPS",                # 딥스
]
