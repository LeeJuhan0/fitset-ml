# ─────────────────────────────────────────────────────────────────────────────
# 전역 설정 + 상수. web·worker 양쪽이 공유(core 레이어).
# ─────────────────────────────────────────────────────────────────────────────
from pydantic_settings import BaseSettings   # BaseSettings: 필드를 .env/환경변수로 자동 오버라이드하는 설정 클래스


class Settings(BaseSettings):
    # 아래 각 필드는 "기본값"이며, 같은 이름의 환경변수(.env)가 있으면 그 값으로 대체된다.
    # MLflow — ADR-0017: EC2 온디맨드 + EBS SQLite
    # EC2에서 MLflow 서버가 sqlite:////mlflow/mlflow.db 로 뜨면 이 URI를 사용
    # 서버가 --static-prefix /mlflow 로 뜨므로 REST API도 그 경로 아래에 있다
    mlflow_tracking_uri: str = "http://localhost:5001/mlflow"  # MlflowClient/start_run이 접속할 추적 서버 주소
    mlflow_artifact_root: str = "s3://fitset-models/mlflow"   # log_model 등 아티팩트가 저장될 루트(S3)

    # S3 버킷 — ADR-0015: raw data / model artifact 분리
    raw_data_bucket: str = "fitset-dataset"    # 검증 통과한 학습 CSV·index.json — 신뢰 영역
    models_bucket: str = "fitset-models"       # 모델 산출물·latest.json 이 들어가는 버킷
    # 유저 자동수집 착지 버킷 — 미검증 데이터 격리 영역. 어드민 승인(승격) 전에는
    # 학습 파이프라인이 이 버킷을 보지 않는다. presigned PUT 발급 권한도 이 버킷에만 준다.
    user_uploads_bucket: str = "fitset-user-uploads"

    # AWS
    aws_region: str = "ap-northeast-2"         # boto3 클라이언트 region

    # 클래스 번호와 운동 slug 매핑 테이블(공개 CDN, GET /model/latest 의 metaUrl 로 내려감)
    class_mapping_url: str = "https://dtcevtkuvdwt9.cloudfront.net/models/class-mapping.json"

    # 유저 JWT 검증(app/core/auth.py) — 백엔드가 발급한 RS256 access 토큰을 JWKS 공개키로 검증
    jwks_url: str = "https://api.fitset.kro.kr/.well-known/jwks.json"   # 백엔드 공개키 배포 지점
    jwt_public_key_pem: str | None = None      # 로컬 개발용 PEM 직접 주입 — 있으면 JWKS 조회를 건너뜀

    # MLflow UI 프록시(app/mlflow_proxy.py) — /mlflow/* 를 이 대상으로 중계
    mlflow_proxy_target: str = "http://localhost:5001"   # 원 서버 주소(경로 프리픽스 없이)
    mlflow_ui_user: str = ""       # Basic 인증 계정 — 둘 중 하나라도 비면 프록시 잠금(fail closed)
    mlflow_ui_password: str = ""

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
