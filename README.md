# FitSet ML Server

운동 자세 분류 모델을 **수집 → 학습 → 평가 → 배포**까지 관리하는 FastAPI 기반 ML 백엔드입니다.
플랫폼(`ios`/`android`)별로 데이터셋과 모델 버전을 독립적으로 운영합니다.

## 아키텍처

**단일 모듈(app/) 안에서 도메인별 수직 슬라이스(package by feature) + 슬라이스 내부 계층형(router→service→utils→repository) + 런타임 분리(web/worker)** 구조입니다. 컨테이너는 이 웹서버와 MLflow 두 개뿐입니다.
상세 구조도·계층 규칙·핵심 설계 포인트는 [코드 아키텍처 문서](docs/architecture.md)를 참고하세요.

## API

관리자 전용 서버입니다. 유저 트래픽은 받지 않으며 컨테이너는 api(정적 대시보드 + API + sqlite 목록 + 워커)와 mlflow 두 개입니다. `{platform}`은 `ios` 또는 `android`만 허용됩니다([deps.py](app/deps.py)).

| prefix | 인증 | 용도 |
|--------|------|------|
| `/api/v1/{platform}` | Basic — 팀 공용 계정, `MLFLOW_UI_USER/PASSWORD` ([core/security.py](app/core/security.py)) | 대시보드·운영 |

대시보드 정적 파일("/")과 MLflow 프록시(`/mlflow/*`)도 같은 Basic 계정으로 보호됩니다(미설정 시 503 잠금).

### 어드민 — 데이터 ([data/router.py](app/data/router.py))
| Method | Path | 설명 |
|--------|------|------|
| `GET` | `/api/v1/{p}/data` | 학습 인덱스의 등록 파일 목록 조회 (신뢰 영역) |
| `GET` | `/api/v1/{p}/data/stats?filename=` | 파일 센서 통계 (트림 적용 채널 요약) |

### 어드민 — 운동 종목 마스터 ([exercises/router.py](app/exercises/router.py))
| Method | Path | 설명 |
|--------|------|------|
| `GET` | `/api/v1/exercises` | 마스터 207종목, 모델 출력 인덱스·class·slug·이름·백엔드 id·phase 지원 여부 |
| `POST` | `/api/v1/exercises/seed?source=` | class-mapping.json 으로 upsert. source 는 `s3://fitset-exercise-media/models/class-mapping.json` 또는 https, 생략 시 `CLASS_MAPPING_URL` |

dataset_files, collect_files, phase_models 는 `exercise_fk` 로 마스터를 참조한다(마스터에 없는 종목은 NULL). 첫 기동 후 한 번 `PYTHONPATH=. python scripts/seed_exercises.py` 또는 seed API 를 호출한다.

### 어드민 — 수집앱 영상 · 구간 라벨링 ([phase/router.py](app/phase/router.py))
수집앱은 IMU CSV와 같은 이름의 영상을 쌍으로 올린다. 종목은 exercises 마스터(207건)에 있으면 전부 올릴 수 있다. 라벨링은 모든 종목에서 MediaPipe 관절 33개를 뽑아 pose.json 으로 남기고, 마스터에 각도 규칙(angle_joints, down_is_decreasing)이 있는 종목만 행마다 phase(0 내려감, 1 올라감, 2 멈춤, -1 미검출)를 붙인다. 규칙이 없는 종목은 관절만 있고 phase 는 -1 이다. 검증된 규칙은 스쿼트(hip,kn,an), 푸시업·덤벨컬(sh,el,wr)이고 시드가 채운다. 새 종목은 마스터 행의 두 열을 채우면 코드 수정 없이 열린다.

| Method | Path | 설명 |
|--------|------|------|
| `GET` | `/api/v1/{p}/phase/presigned-url?class=&deviceId=` | 파일명 채번 + CSV·영상 presigned PUT 2개 발급. 키는 `{platform}/{index}_{class}/{filename}` 이고 폴더는 `scripts/init_buckets.py` 가 4개 버킷에 207종목 x 2플랫폼으로 미리 만든다 |
| `POST` | `/api/v1/{p}/phase/upload-confirm` | `{filename, videoStart, rows}` 두 PUT 완료 확정. videoStart 는 영상 첫 프레임 unix 초 |
| `GET` | `/api/v1/{p}/phase/files` | 목록 전체 + 상태별 개수 (pending, labeling, labeled, failed) |
| `POST` | `/api/v1/{p}/phase/label` | `{filenames}` 라벨링 시작(202). 워커가 labeled 버킷으로 CSV(phase 열)·영상·pose.json 을 옮기고 원본을 지운다 |
| `GET` | `/api/v1/{p}/phase/video-url?filename=` | 대시보드 재생용 presigned GET (라벨링 후엔 labeled 버킷) |
| `GET` | `/api/v1/{p}/phase/pose?filename=` | 프레임별 33개 관절 좌표와 phase (대시보드 오버레이) |
| `POST` | `/api/v1/{p}/phase/promote` | `{filenames}` 승격. 라벨 parquet 를 fitset-dataset 으로 복사하고 dataset_files 에 등록(phase_labeled). 라벨 미지원 종목은 CSV 를 parquet 로 바꿔 승격 |
| `POST` | `/api/v1/{p}/phase/train` | `{class, filenames?, epochs, lr, window, stride}` 종목별 렙카운팅(0 1 2) 모델 학습 시작(202). 파일 생략 시 그 종목의 phase_labeled 전부 |
| `GET` | `/api/v1/{p}/phase/models?class=` | 렙카운팅 모델 버전 목록과 지표 |
| `GET` | `/api/v1/{p}/phase/models/{id}/download-url?format=pt\|onnx\|mlpackage` | 산출물 presigned GET (버킷 fitset-phase-models) |

렙카운팅 모델은 분류 모델과 같은 CNN-LSTM(FitSetModel)에 정답만 phase(0, 1, 2)를 쓴다. 입력 [1, 50, 6], 학습 stride 5, 워치 추론 stride 10. 산출물은 `s3://fitset-phase-models/{platform}/{index}_{class}/{version}/FitSetPhase.{pt,onnx,mlpackage.zip}` 과 meta.json 이고 위치는 `phase_models` 테이블이 정본이다. 라벨 결과와 승격 데이터는 CSV 가 아니라 parquet 로 저장한다.

### 어드민 — 학습·배포 ([training/router.py](app/training/router.py) · [deployment/router.py](app/deployment/router.py))
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

`SQUAT`, `PUSHUP`, `DUMBBELL_CURL`, `SIDE_LATERAL_RAISE`, `REST` ([config.py](app/core/config.py))

## 데이터 흐름

```
[수집]    presigned-url 발급 → 클라이언트가 S3에 직접 업로드 → upload-confirm 으로 목록(DB) 등록
[라벨링]  phase/presigned-url → CSV+영상 PUT → upload-confirm → 대시보드 라벨링 버튼 → phase_labeler 워커 → labeled 버킷
[학습]    POST /train → trainer 서브프로세스 → MLflow에 메트릭 기록 → GET /train/status·/runs 로 모니터링
[배포]    POST /deploy → S3 latest 갱신 → 클라이언트가 GET /model/latest 로 최신 모델 확인
```

## 파일 목록 DB

파일 목록은 2026-09-22 부터 S3 index.json 이 아니라 DB(SQLModel 엔티티, [core/models.py](app/core/models.py)·[data/models.py](app/data/models.py)·[phase/models.py](app/phase/models.py))가 정본이다. S3 에는 객체만 둔다. 관리자 전용이라 트래픽이 작아 sqlite 파일을 쓴다. EC2 는 api 컨테이너의 `/data` 볼륨(`sqlite+aiosqlite:////data/fitset_ml.db`), 로컬·테스트는 작업 디렉토리 파일이다. 접근은 SQLAlchemy 비동기 엔진과 AsyncSession 이고, MySQL 이 필요해지면 `DATABASE_URL` 을 `mysql+aiomysql://` 로 바꾸면 된다. 스키마는 Alembic 마이그레이션(`alembic/versions/`)이 정본이다. 컨테이너가 시작할 때 엔트리포인트(`docker/entrypoint.sh` → `scripts/migrate.py`)가 `upgrade head` 를 먼저 돌린다. `create_all` 로 만든 기존 DB 는 초기 리비전으로 표시한 뒤 적용한다. 로컬에서 서버를 띄우기 전에는 `PYTHONPATH=. python scripts/migrate.py` 를 한 번 돌린다.

모델을 바꾸면 로컬에서 `alembic upgrade head` 로 DB 를 최신으로 맞춘 뒤 `alembic revision --autogenerate -m "설명"` 으로 스크립트를 만들고, 생성된 파일을 확인해 모델과 함께 커밋한다. 배포하면 컨테이너 시작 때 자동 적용된다.

| 파일 | 용도 |
|------|------|
| [db/init-mysql.sql](db/init-mysql.sql) | EC2 MySQL 에서 root 로 한 번. 데이터베이스 `fitset_ml` 과 계정 생성 |

스키마를 SQL 로 검토해야 하면 `alembic upgrade head --sql` 로 마이그레이션을 SQL 로 뽑는다. `db/` 는 계정 생성용 SQL 만 둔다.

EC2 에 MySQL 을 직접 깔아 쓰는 순서.

1. `sudo apt install mysql-server` 뒤 `sudo mysql < db/init-mysql.sql` (비밀번호는 파일에서 바꾼다).
2. 테이블은 컨테이너 시작 때 마이그레이션이 만든다. 권한·문자셋은 `mysql -u fitset_ml -p fitset_ml -e "SELECT 1"` 로 접속만 확인한다.
3. api 컨테이너 env 를 `DATABASE_URL=mysql+aiomysql://fitset_ml:비밀번호@호스트:3306/fitset_ml?charset=utf8mb4` 로. 컨테이너에서 호스트 MySQL 로 붙으려면 호스트는 `host.docker.internal`(compose 에 `extra_hosts: ["host.docker.internal:host-gateway"]`) 이고 MySQL 의 `bind-address` 가 docker 브리지에서 닿아야 한다.
4. 기존 index.json 이관과 마스터 시드. 이미지에 scripts/ 가 들어 있으므로 EC2 에서 `docker exec fitset-ml-admin python scripts/migrate_index_to_db.py` 와 `docker exec fitset-ml-admin python scripts/seed_exercises.py` 로 돌린다(컨테이너 env 의 DATABASE_URL 사용). 버킷 폴더가 없으면 `docker exec fitset-ml-admin python scripts/init_buckets.py`.

| 테이블 | 내용 | 관계 |
|--------|------|------|
| `exercises` | 운동 종목 마스터(출력 인덱스, class, slug, 이름, 각도 규칙) | dataset_files·collect_files·phase_models 가 참조 |
| `platforms` | ios, android | devices·dataset_files·collect_files·phase_models 의 부모 |
| `devices` | 수집 기기(채번 주인) | platform 에 속함, dataset_files·collect_files 의 부모 |
| `dataset_files` | 학습 데이터셋(fitset-dataset) | platform, device |
| `collect_files` | 수집앱 IMU+영상 쌍, 상태(pending·labeling·labeled·failed), 승격 시 dataset_file 연결 | platform, device, label(1:1), dataset_file(1:1) |
| `phase_labels` | 라벨 결과 위치(labeled 버킷 parquet·영상·pose 키)와 요약 | collect_file |
| `phase_models` | 종목별 렙카운팅 모델 버전, pt·onnx·mlpackage 키, 지표 | platform, files(N:M dataset_files) |
| `phase_model_files` | 모델 학습에 쓰인 파일 링크 | phase_model, dataset_file |

기존 index.json 은 `PYTHONPATH=. python scripts/migrate_index_to_db.py` 로 한 번 옮긴다(멱등). 테이블 정의는 [docs/file-ledger.dbml](docs/file-ledger.dbml).

## 인프라

- **MLflow**: 학습 추적 서버, 별도 컨테이너([mlflow](mlflow/Dockerfile))
- **DB**: 파일 목록 sqlite, api 컨테이너 `/data` 볼륨
- **S3**: `fitset-dataset`(raw data) / `fitset-models`(분류 모델 artifact) 분리 (ADR-0015), 수집앱 영상 라벨링은 `fitset-collect-imu` / `fitset-collect-video` / `fitset-collect-labeled`, 렙카운팅 모델은 `fitset-phase-models`. 다섯 버킷 모두 `{platform}/{index:03d}_{CLASS}/` 폴더가 207종목 x ios·android 로 미리 있고(dataset 은 `raw/` 아래), `scripts/init_buckets.py` 로 다시 만든다. 새 파일은 이 폴더로 가고 이관된 구 데이터는 `raw/{CLASS}/` 에 남아 목록의 저장된 키로 읽는다
- **AWS Region**: `ap-northeast-2`
- 설정은 [config.py](app/core/config.py)의 `Settings`(`.env` 오버라이드 가능)에서 관리

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
| `fitset-ml-admin-api` | [Dockerfile](Dockerfile) | 8000 | `GET /api/health` |
| `fitset-mlflow` | [mlflow/Dockerfile](mlflow/Dockerfile) | 5001 | `GET /mlflow/health` |

```bash
docker buildx build --platform linux/amd64 -t fitset-ml-admin-api .
aws s3 cp s3://fitset-models/backup/mlflow-20260824.db mlflow/mlflow.db
docker buildx build --platform linux/amd64 -f mlflow/Dockerfile -t fitset-mlflow .
```

admin-api 환경변수는 아래와 같습니다. AWS 자격은 파드 역할(IRSA 또는 Pod Identity)로 주입하고 S3 `fitset-dataset`, `fitset-models`, `fitset-collect-imu`, `fitset-collect-video`, `fitset-collect-labeled`, `fitset-phase-models` 접근 권한이 필요합니다(fitset-ml-task-role, fitset-dev-ml-ec2 에 2026-09-22 추가됨).

| 변수 | 예시 | 설명 |
|------|------|------|
| `MLFLOW_TRACKING_URI` | `http://mlflow:5001/mlflow` | 추적 서버 주소, static prefix 포함 |
| `MLFLOW_PROXY_TARGET` | `http://mlflow:5001` | `/mlflow/*` 역프록시 대상, prefix 없이 |
| `MLFLOW_UI_USER`, `MLFLOW_UI_PASSWORD` | Secret | Basic 계정, 비어 있으면 503으로 잠김 |
| `CLASS_MAPPING_URL` | `https://d31w3ih1t93w7x.cloudfront.net/models/class-mapping.json` | 앱 폴링용 공개 매핑. 2026-09-22 새 CloudFront 도메인으로 기본값 교체 |
| `RAW_DATA_BUCKET`, `MODELS_BUCKET`, `AWS_REGION` | 기본값 사용 가능 | [config.py](app/core/config.py) 참고 |
| `COLLECT_IMU_BUCKET`, `COLLECT_VIDEO_BUCKET`, `COLLECT_LABELED_BUCKET`, `PHASE_MODELS_BUCKET` | 기본값 사용 가능 | 수집앱 영상 라벨링 버킷 3종과 렙카운팅 모델 버킷 |
| `DATABASE_URL` | `sqlite+aiosqlite:////data/fitset_ml.db` | 파일 목록 DB(비동기 드라이버). MySQL 은 `mysql+aiomysql://...` |
| `POSE_MODEL_PATH` | `/srv/models/pose_landmarker_full.task` | MediaPipe 포즈 모델. 없으면 워커가 내려받는다 |

mlflow 환경변수는 `BACKEND_STORE_URI`, `ARTIFACT_ROOT`, `ALLOWED_HOSTS`, `CORS_ORIGINS`입니다. `BACKEND_STORE_URI`를 주지 않으면 이미지에 구운 sqlite로 뜨고 재시작 시 기록이 초기화되므로 MySQL(`mysql+pymysql://`)이나 볼륨을 붙여야 합니다. `ALLOWED_HOSTS`에는 admin-api가 접속하는 서비스 DNS와 포트를 넣습니다. 학습은 admin-api 파드 안에서 서브프로세스로 돌기 때문에 메모리 2GB 이상을 권장합니다.

## 로컬 실행

```bash
uvicorn app.main:app --reload
docker compose up --build   # mlflow와 admin-api를 한 번에
```

## 테스트

```bash
pytest
```

`tests/`에 API·S3 헬퍼·플랫폼 검증 테스트가 있습니다.
