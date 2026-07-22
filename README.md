# FitSet ML Server

운동 자세 분류 모델을 **수집 → 학습 → 평가 → 배포**까지 관리하는 FastAPI 기반 ML 백엔드입니다.
플랫폼(`ios`/`android`)별로 데이터셋과 모델 버전을 독립적으로 운영합니다.

## 아키텍처

**도메인별 수직 슬라이스(package by feature) + 슬라이스 내부 계층형(router→service→domain→repository) + 런타임 분리(web/worker)** 구조입니다.
상세 구조도·계층 규칙·핵심 설계 포인트는 [코드 아키텍처 문서](docs/architecture.md)를 참고하세요.

## API

모든 엔드포인트는 `/api/v1/{platform}/...` 형태이며, `{platform}`은 `ios` 또는 `android`만 허용됩니다([deps.py](app/deps.py)).

### 데이터 ([data/router.py](app/data/router.py))
| Method | Path | 설명 |
|--------|------|------|
| `GET` | `/data` | S3 인덱스의 등록된 데이터 파일 목록 조회 |
| `GET` | `/data/presigned-url?filename=&class=` | S3 직접 업로드용 presigned URL 발급 (300초). 경로: `{platform}/raw/{class}/{filename}` |
| `POST` | `/data/upload-confirm` | 업로드 완료된 파일을 인덱스에 등록 (`collectedAt`, `trainedInVersion=null`) |

### 학습 ([training/router.py](app/training/router.py))
| Method | Path | 설명 |
|--------|------|------|
| `POST` | `/train` | 학습 시작. 파일 검증 후 MLflow run 생성, `trainer`를 서브프로세스로 실행, `202` 반환. 동일 플랫폼 중복 실행 시 `409`. |
| `GET` | `/train/status?jobId=` | MLflow run 상태/메트릭(epoch, train·val loss, val accuracy) 조회 |

### 학습 이력 ([training/router.py](app/training/router.py))
| Method | Path | 설명 |
|--------|------|------|
| `GET` | `/runs` | 최근 50개 run 목록 + 파라미터/메트릭, `val_accuracy` 기준 best run 표시 |
| `GET` | `/runs/{run_id}/history?metric=` | 특정 run의 메트릭 시계열(step별) 조회 |

### 배포 ([deployment/router.py](app/deployment/router.py))
| Method | Path | 설명 |
|--------|------|------|
| `POST` | `/deploy` | 버전에 해당하는 모델을 배포(latest로 기록). 모델 경로 확장자: iOS `mlpackage`, Android `tflite` |

### 모델 조회 ([deployment/router.py](app/deployment/router.py))
| Method | Path | 설명 |
|--------|------|------|
| `GET` | `/model/latest?currentVersion=` | 최신 배포 버전·모델 URL·최신 여부(`isUpToDate`) 반환. 클라이언트 버전 리포팅 기록 |
| `GET` | `/model/version-stats` | 최근 24시간 리포트 기준 버전 분포(count·ratio) 조회 |

## 분류 종목 (CLASSES)

`SQUAT`, `PUSHUP`, `DUMBBELL_CURL`, `SIDE_LATERAL_RAISE`, `REST` ([config.py](app/core/config.py))

## 데이터 흐름

```
[수집]  presigned-url 발급 → 클라이언트가 S3에 직접 업로드 → upload-confirm 으로 인덱스 등록
[학습]  POST /train → trainer 서브프로세스 → MLflow에 메트릭 기록 → GET /train/status·/runs 로 모니터링
[배포]  POST /deploy → S3 latest 갱신 → 클라이언트가 GET /model/latest 로 최신 모델 확인
```

## 인프라

- **MLflow**: 학습 추적 (EC2 온디맨드 + EBS SQLite — ADR-0017)
- **S3**: `fitset-dataset`(raw data) / `fitset-models`(모델 artifact) 분리 (ADR-0015)
- **AWS Region**: `ap-northeast-2`
- 설정은 [config.py](app/core/config.py)의 `Settings`(`.env` 오버라이드 가능)에서 관리

## 문서

- [코드 아키텍처](docs/architecture.md)
- [API 명세 — 데이터 수집](docs/api-spec-06-data-collection.md)
- [API 명세 — ML 학습·서빙](docs/api-spec-07-ml-training-serving.md)
- [코드 컨벤션](docs/코드%20컨벤션.md)

## 실행

```bash
uvicorn app.main:app --reload
```

## 테스트

```bash
pytest
```

`tests/`에 API·S3 헬퍼·플랫폼 검증 테스트가 있습니다.
