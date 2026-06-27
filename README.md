# FitSet ML Server

운동 자세 분류 모델을 **수집 → 학습 → 평가 → 배포**까지 관리하는 FastAPI 기반 ML 백엔드입니다.
플랫폼(`ios`/`android`)별로 데이터셋과 모델 버전을 독립적으로 운영합니다.

## 아키텍처 패턴

**Layered Architecture(계층형) + Producer–Worker** 구조입니다. (MVC가 아닙니다 — 별도 View가 없고, 학습이 비동기 워커로 분리됩니다.)

```
app/
├── main.py          # Composition Root — 앱 조립, 라우터/미들웨어 등록
│
├── api/             # ── Presentation Layer (Controller) ──
│   ├── deps.py      #    공통 의존성 (validate_platform)
│   ├── data.py      #    데이터 업로드/조회
│   ├── train.py     #    학습 시작/진행률
│   ├── runs.py      #    학습 이력/메트릭
│   ├── deploy.py    #    모델 배포
│   └── model.py     #    최신 모델/버전 통계
│
├── core/            # ── Infrastructure Layer ──
│   ├── config.py    #    설정(settings), PLATFORMS, CLASSES
│   └── s3.py        #    S3 인덱스/메타 read·write, presigned URL
│
└── worker/          # ── Domain / Job Layer (별도 프로세스) ──
    ├── trainer.py   #    학습 엔트리포인트 (subprocess로 실행)
    ├── model_def.py #    모델 정의
    ├── preprocess.py#    전처리
    └── convert.py   #    모델 변환 (tflite / mlpackage)
```

| 계층 | 폴더 | 역할 | MVC 대응 |
|------|------|------|----------|
| Presentation | `api/` | HTTP 라우팅·요청 검증·응답 직렬화 | Controller |
| Infrastructure | `core/` | 설정, S3 등 외부자원 접근 | Service / Repository |
| Domain / Job | `worker/` | 모델 정의·학습·전처리 (도메인 로직) | Model(도메인) |
| View | `static/` | 정적 프론트엔드 (mount만) | View (분리됨) |

### 핵심 설계 포인트

1. **Layered Architecture** — `api` → `core` → `worker` 단방향 의존.
2. **Dependency Injection** — FastAPI `Depends(validate_platform)`로 플랫폼 검증을 횡단 주입.
3. **Producer–Worker (Job Offloading)** — 학습은 `subprocess.Popen`으로 `app.worker.trainer`를 별도 프로세스로 실행하고, API는 즉시 `202 Accepted`를 반환. (Celery/RQ를 서브프로세스로 단순화한 형태.)
4. **상태 외부화** — 학습 추적/메트릭은 **MLflow**, 데이터·모델 메타데이터는 **S3 인덱스**에 저장. (단, `_running`·`_version_stats` 는 인메모리라 서버 재시작 시 초기화됨.)

> FastAPI 진영의 표준 디렉터리 구조(`full-stack-fastapi-template`, `netflix/dispatch` 등과 동일 계열)를 따르며, 워커만 메시지큐 대신 서브프로세스로 경량화했습니다.

## API

모든 엔드포인트는 `/api/v1/{platform}/...` 형태이며, `{platform}`은 `ios` 또는 `android`만 허용됩니다([deps.py](app/api/deps.py)).

### 데이터 ([data.py](app/api/data.py))
| Method | Path | 설명 |
|--------|------|------|
| `GET` | `/data` | S3 인덱스의 등록된 데이터 파일 목록 조회 |
| `GET` | `/data/presigned-url?filename=&class=` | S3 직접 업로드용 presigned URL 발급 (300초). 경로: `{platform}/raw/{class}/{filename}` |
| `POST` | `/data/upload-confirm` | 업로드 완료된 파일을 인덱스에 등록 (`collectedAt`, `trainedInVersion=null`) |

### 학습 ([train.py](app/api/train.py))
| Method | Path | 설명 |
|--------|------|------|
| `POST` | `/train` | 학습 시작. 파일 검증 후 MLflow run 생성, `trainer`를 서브프로세스로 실행, `202` 반환. 동일 플랫폼 중복 실행 시 `409`. |
| `GET` | `/train/status?jobId=` | MLflow run 상태/메트릭(epoch, train·val loss, val accuracy) 조회 |

### 학습 이력 ([runs.py](app/api/runs.py))
| Method | Path | 설명 |
|--------|------|------|
| `GET` | `/runs` | 최근 50개 run 목록 + 파라미터/메트릭, `val_accuracy` 기준 best run 표시 |
| `GET` | `/runs/{run_id}/history?metric=` | 특정 run의 메트릭 시계열(step별) 조회 |

### 배포 ([deploy.py](app/api/deploy.py))
| Method | Path | 설명 |
|--------|------|------|
| `POST` | `/deploy` | 버전에 해당하는 모델을 배포(latest로 기록). 모델 경로 확장자: iOS `mlpackage`, Android `tflite` |

### 모델 조회 ([model.py](app/api/model.py))
| Method | Path | 설명 |
|--------|------|------|
| `GET` | `/model/latest?currentVersion=` | 최신 배포 버전·모델 URL·최신 여부(`isUpToDate`) 반환. 클라이언트 버전 리포팅 집계 |
| `GET` | `/model/version-stats` | 클라이언트들의 버전 분포(count·ratio) 조회 |

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

## 실행

```bash
uvicorn app.main:app --reload
```

## 테스트

```bash
pytest
```

`tests/`에 API·S3 헬퍼·플랫폼 검증 테스트가 있습니다.
