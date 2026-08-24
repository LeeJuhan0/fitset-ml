# FitSet ML Server

운동 자세 분류 모델을 **수집 → 학습 → 평가 → 배포**까지 관리하는 FastAPI 기반 ML 백엔드입니다.
플랫폼(`ios`/`android`)별로 데이터셋과 모델 버전을 독립적으로 운영합니다.

## 아키텍처

**도메인별 수직 슬라이스(package by feature) + 슬라이스 내부 계층형(router→service→domain→repository) + 런타임 분리(web/worker)** 구조입니다.
상세 구조도·계층 규칙·핵심 설계 포인트는 [코드 아키텍처 문서](docs/architecture.md)를 참고하세요.

## API

경로는 호출 주체별 2계층입니다. `{platform}`은 `ios` 또는 `android`만 허용됩니다([deps.py](app/deps.py)).

| 계층 | prefix | 인증 | 용도 |
|------|--------|------|------|
| 유저 | `/api/v1/{platform}` | Bearer JWT — 백엔드 JWKS 공개키(RS256)로 직접 검증, `sub`=userId ([core/auth.py](app/core/auth.py)) | 앱 직접 호출 |
| 어드민 | `/api/admin/v1/{platform}` | Basic — 팀 공용 계정, `MLFLOW_UI_USER/PASSWORD` ([core/security.py](app/core/security.py)) | 대시보드·운영 |

대시보드 정적 파일("/")과 MLflow 프록시(`/mlflow/*`)도 같은 Basic 계정으로 보호됩니다(미설정 시 503 잠금).

### 유저 — 데이터 수집·모델 폴링
| Method | Path | 설명 |
|--------|------|------|
| `GET` | `/api/v1/{p}/data/presigned-url?class=&deviceId=` | 격리 버킷 업로드용 presigned URL 발급 (300초). 경로: `fitset-user-uploads/{platform}/{userId}/{filename}`, 채번 주인은 토큰 userId |
| `POST` | `/api/v1/{p}/data/upload-confirm` | 업로드 대장(uploads-index.json)의 예약 항목을 `uploaded=true`로 확정 |
| `GET` | `/api/v1/{p}/model/latest?currentVersion=` | 최신 배포 버전·모델 presigned URL·`metaUrl`·`isUpToDate` 반환. 버전 리포팅 기록 |

### 어드민 — 데이터·승격 ([data/router.py](app/data/router.py))
| Method | Path | 설명 |
|--------|------|------|
| `GET` | `/api/admin/v1/{p}/data` | 학습 인덱스의 등록 파일 목록 조회 (신뢰 영역) |
| `GET` | `/api/admin/v1/{p}/data/stats?filename=` | 파일 센서 통계 (트림 적용 채널 요약) |
| `GET` | `/api/admin/v1/{p}/uploads?status=` | 유저 업로드 대장 조회 (pending/approved/rejected) |
| `POST` | `/api/admin/v1/{p}/uploads/{filename}/approve\|reject` | 승격 승인·반려 — 인터페이스만 확정, 처리 로직 구현 전(501) |

### 어드민 — 학습·배포 ([training/router.py](app/training/router.py) · [deployment/router.py](app/deployment/router.py))
| Method | Path | 설명 |
|--------|------|------|
| `POST` | `/api/admin/v1/{p}/train` | 학습 시작(202). 동일 플랫폼 중복 실행 시 `409` |
| `GET` | `/api/admin/v1/{p}/train/status?jobId=` | MLflow run 상태/메트릭 조회 |
| `GET` | `/api/admin/v1/{p}/runs` | 최근 50개 run 목록 + best run |
| `GET` | `/api/admin/v1/{p}/runs/{run_id}/history?metric=` | 메트릭 시계열 조회 |
| `POST` | `/api/admin/v1/{p}/deploy` | 지정 버전 배포(latest 기록·롤백 포함) |
| `GET` | `/api/admin/v1/{p}/model/latest` | 대시보드용 최신 모델 조회(분포 집계 미기록) |
| `GET` | `/api/admin/v1/{p}/model/version-stats` | 최근 24시간 리포트 기준 버전 분포 조회 |

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
