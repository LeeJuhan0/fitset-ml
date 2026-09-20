# FitSet ML Server

운동 자세 분류 모델을 **수집 → 학습 → 평가 → 배포**까지 관리하는 FastAPI 기반 ML 백엔드입니다.
플랫폼(`ios`/`android`)별로 데이터셋과 모델 버전을 독립적으로 운영합니다.

## 아키텍처

**도메인별 수직 슬라이스(package by feature) + 슬라이스 내부 계층형(router→service→domain→repository) + 런타임 분리(web/worker)** 구조입니다.
상세 구조도·계층 규칙·핵심 설계 포인트는 [코드 아키텍처 문서](docs/architecture.md)를 참고하세요.

## API

모든 API는 어드민 전용입니다. `{platform}`은 `ios` 또는 `android`만 허용됩니다([deps.py](libs/common/app/deps.py)).
유저용 서비스(user_api, `/ml/v1`)는 2026-09-19에 제거했습니다.

| prefix | 인증 | 용도 |
|--------|------|------|
| `/api/v1/{platform}` | Basic — 팀 공용 계정, `MLFLOW_UI_USER/PASSWORD` ([core/security.py](libs/common/app/core/security.py)) | 대시보드·운영 |

대시보드 정적 파일("/")과 MLflow 프록시(`/mlflow/*`)도 같은 Basic 계정으로 보호됩니다(미설정 시 503 잠금).

### 어드민 — 데이터·승격 ([data/router.py](libs/common/app/data/router.py))
| Method | Path | 설명 |
|--------|------|------|
| `GET` | `/api/v1/{p}/data` | 학습 인덱스의 등록 파일 목록 조회 (신뢰 영역) |
| `GET` | `/api/v1/{p}/data/stats?filename=` | 파일 센서 통계 (트림 적용 채널 요약) |
| `GET` | `/api/v1/{p}/uploads?status=` | 유저 업로드 대장 조회 (pending/approved/rejected) |
| `POST` | `/api/v1/{p}/uploads/{filename}/approve\|reject` | 승격 승인·반려 — 인터페이스만 확정, 처리 로직 구현 전(501) |

### 어드민 — 학습·배포 ([training/router.py](libs/common/app/training/router.py) · [deployment/router.py](libs/common/app/deployment/router.py))
| Method | Path | 설명 |
|--------|------|------|
| `POST` | `/api/v1/{p}/train` | 학습 시작(202). 동일 플랫폼 중복 실행 시 `409` |
| `GET` | `/api/v1/{p}/train/status?jobId=` | MLflow run 상태/메트릭 조회 |
| `GET` | `/api/v1/{p}/runs` | 최근 50개 run 목록 + best run |
| `GET` | `/api/v1/{p}/runs/{run_id}/history?metric=` | 메트릭 시계열 조회 |
| `POST` | `/api/v1/{p}/deploy` | 지정 버전 배포(latest 기록·롤백 포함) |
| `GET` | `/api/v1/{p}/model/latest` | 대시보드용 최신 모델 조회(분포 집계 미기록) |
| `GET` | `/api/v1/{p}/model/version-stats` | 최근 24시간 리포트 기준 버전 분포 조회 |

## 분류 종목 (CLASSES)

`SQUAT`, `PUSHUP`, `DUMBBELL_CURL`, `SIDE_LATERAL_RAISE`, `REST` ([config.py](libs/common/app/core/config.py))

## 데이터 흐름

```
[수집]  presigned-url 발급 → 클라이언트가 S3에 직접 업로드 → upload-confirm 으로 인덱스 등록
[학습]  POST /train → trainer 서브프로세스 → MLflow에 메트릭 기록 → GET /train/status·/runs 로 모니터링
[배포]  POST /deploy → S3 latest 갱신 → 클라이언트가 GET /model/latest 로 최신 모델 확인
```

## 인프라

- **MLflow**: 학습 추적 서버, 별도 컨테이너([services/mlflow](services/mlflow/Dockerfile))
- **S3**: `fitset-dataset`(raw data) / `fitset-models`(모델 artifact) 분리 (ADR-0015)
- **AWS Region**: `ap-northeast-2`
- 설정은 [config.py](libs/common/app/core/config.py)의 `Settings`(`.env` 오버라이드 가능)에서 관리

## 문서

- [코드 아키텍처](docs/architecture.md)
- [API 명세 — 데이터 수집](docs/api-spec-06-data-collection.md)
- [API 명세 — ML 학습·서빙](docs/api-spec-07-ml-training-serving.md)
- [코드 컨벤션](docs/코드%20컨벤션.md)

## 컨테이너

이미지는 2종이고 빌드 컨텍스트는 레포 루트입니다. `develop`에 머지되면 [cd.yml](.github/workflows/cd.yml)이 ECR에 `{커밋 SHA}` 태그로 푸시하고, SSM SendCommand로 dev 인스턴스의 컨테이너를 교체합니다.

무엇을 어떻게 띄울지는 `s3://fitset-deploy-artifacts/dev/ml-compose/`의 `docker-compose.yml`·`up.sh`가 정하고, 인스턴스·ALB·IAM은 [fitset-infra-tf](https://github.com/asm-hangang/fitset-infra-tf)가 만듭니다.

dev 주소는 `https://ml-dev.fitset.kro.kr`이며 ALB가 **호스트로** 가릅니다 — `/api/v1`이 백엔드와 겹치고 `/`에 대시보드를 마운트해서 경로로는 갈리지 않습니다. `/api/health`만 공개고 나머지는 Basic 인증 뒤에 있습니다.

비밀값(`MLFLOW_UI_USER`·`MLFLOW_UI_PASSWORD`)은 SSM SecureString에서 읽어 compose 프로세스 환경으로만 넘깁니다 — 디스크에 쓰지 않습니다.

| 이미지 | Dockerfile | 포트 | 헬스체크 |
|--------|-----------|------|----------|
| `fitset-ml-admin-api` | [services/admin_api/Dockerfile](services/admin_api/Dockerfile) | 8000 | `GET /api/health` |
| `fitset-mlflow` | [services/mlflow/Dockerfile](services/mlflow/Dockerfile) | 5001 | `GET /mlflow/health` |

```bash
docker buildx build --platform linux/amd64 -f services/admin_api/Dockerfile -t fitset-ml-admin-api .
aws s3 cp s3://fitset-models/backup/mlflow-20260824.db services/mlflow/mlflow.db
docker buildx build --platform linux/amd64 -f services/mlflow/Dockerfile -t fitset-mlflow .
```

admin-api 환경변수는 아래와 같습니다. AWS 자격은 파드 역할(IRSA 또는 Pod Identity)로 주입하고 S3 `fitset-dataset`, `fitset-models`, `fitset-user-uploads` 접근 권한이 필요합니다.

| 변수 | 예시 | 설명 |
|------|------|------|
| `MLFLOW_TRACKING_URI` | `http://mlflow:5001/mlflow` | 추적 서버 주소, static prefix 포함 |
| `MLFLOW_PROXY_TARGET` | `http://mlflow:5001` | `/mlflow/*` 역프록시 대상, prefix 없이 |
| `MLFLOW_UI_USER`, `MLFLOW_UI_PASSWORD` | Secret | Basic 계정, 비어 있으면 503으로 잠김 |
| `CLASS_MAPPING_URL` | `https://{미디어 CDN}/models/class-mapping.json` | 코드 기본값이 옛 CloudFront 도메인이라 반드시 덮어쓴다 |
| `RAW_DATA_BUCKET`, `MODELS_BUCKET`, `USER_UPLOADS_BUCKET`, `AWS_REGION` | 기본값 사용 가능 | [config.py](libs/common/app/core/config.py) 참고 |

mlflow 환경변수는 `BACKEND_STORE_URI`, `ARTIFACT_ROOT`, `ALLOWED_HOSTS`, `CORS_ORIGINS`입니다. `BACKEND_STORE_URI`를 주지 않으면 이미지에 구운 sqlite로 뜨고 재시작 시 기록이 초기화되므로 MySQL(`mysql+pymysql://`)이나 볼륨을 붙여야 합니다. `ALLOWED_HOSTS`에는 admin-api가 접속하는 서비스 DNS와 포트를 넣습니다. 학습은 admin-api 파드 안에서 서브프로세스로 돌기 때문에 메모리 2GB 이상을 권장합니다.

## 로컬 실행

```bash
PYTHONPATH=libs/common:services/admin_api uvicorn admin_api.main:app --reload
docker compose up --build   # mlflow와 admin-api를 한 번에
```

## 테스트

```bash
pytest
```

`tests/`에 API·S3 헬퍼·플랫폼 검증 테스트가 있습니다.
