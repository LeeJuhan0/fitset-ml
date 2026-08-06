# 07. ML 모델 학습 및 서빙 API 명세 (Training & Serving)

## 1. 문서 정보

| 항목 | 내용 |
|------|------|
| 프로젝트명 | FitSet |
| 문서 범위 | 모델 학습 시작·모니터링, 학습 이력, 배포, 클라이언트 모델 서빙 — ML 서버(fitset-ml-server) |
| API 버전 | v1 |
| Base URL | 환경별 ML 서버 호스트 + `/api/v1/{platform}` |
| 인증 방식 | 없음(MVP — 내부 관리자 대시보드·앱 전용) |
| Content-Type | `application/json` |
| 연관 에픽 | FIT-33 ML 모델 학습 및 서빙 |
| 최종 수정일 | 2026년 7월 12일 |
| 작성자 | @이주한 |

## 2. 공통 규칙

> 공통 envelope·오류 형식·platform 경로 변수·CLASSES는 **06. 센서 데이터 수집 API 명세 §2~3**을 정본으로 한다. 이 절은 학습·서빙 도메인에만 추가되는 규칙이다.

### 2.1 학습·배포·서빙 모델

```
[학습]  POST /train (202 접수) → trainer 서브프로세스가 학습 → MLflow에 메트릭 기록
        → GET /train/status, GET /runs 로 모니터링
[배포]  POST /deploy → S3 latest.json 갱신 (특정 버전을 latest로 기록)
[서빙]  앱이 GET /model/latest 폴링 → presigned URL로 모델 다운로드 → 기기에서 교체
        (서버 push 없음 — 폴링 방식)
```

| 항목 | 규약 |
|------|------|
| jobId | 학습 시작 시 생성되는 **MLflow run ID** 문자열. 상태 조회의 키 |
| version | 학습 산출물 버전 문자열 `v{major}.{minor}` — 학습 시작 시 서버가 자동 채번(마지막 버전의 minor +1, 최초 `v1.0`) |
| 학습 상태 | `running` / `completed` / `failed` (MLflow RUNNING/FINISHED/FAILED 매핑) |
| 동시 학습 | 플랫폼당 1개 — 진행 중 재요청 시 `409` |
| 모델 포맷 | iOS `FitSet.mlpackage.zip` / Android `FitSet.tflite` |
| 모델 저장 경로 | `s3://fitset-models/{platform}/{version}/FitSet.{ext}` |
| 모델 다운로드 | `GET /model/latest`가 presigned **GET** URL(1시간 유효)로 변환해 내려줌 — 버킷은 프라이빗 유지, HEAD 요청 불가 |

### 2.2 상태 저장 위치와 휘발성 주의

| 데이터 | 저장소 | 휘발성 |
|--------|--------|--------|
| 학습 메트릭·이력 | MLflow (EC2 + SQLite) | 영구 |
| 배포 정보(latest.json)·모델 파일 | S3 `fitset-models` | 영구 (서버는 60초 TTL 캐시, 배포 시 즉시 반영) |
| 진행 중 학습 추적(`totalEpochs` 분모)·버전 분포 집계 | 서버 인메모리 | **서버 재시작 시 초기화** — 재시작 후 `/train/status`의 `totalEpochs`는 0, `/model/version-stats`는 빈 분포에서 시작해 기기들이 폴링하며 다시 채워짐 |

## 3. 공통 응답 형식

팀 공통 규약(ai-server·백엔드와 동일) — 성공은 `{traceId, data}`, 오류는 `{traceId, error: {code, message, details}}`.
`traceId`는 요청 헤더 `X-Trace-Id`를 이어받거나 서버가 발급하며 응답 헤더로도 돌려준다.
`error.code`는 상태코드에서 유도한 시맨틱 코드(400 INVALID_REQUEST, 404 NOT_FOUND 등), 검증 오류는 `422`가 아니라 `400 INVALID_REQUEST`다.

## 4. API 상세 명세

### 4.1 학습 시작

#### 기본 정보

| 항목 | 내용 |
|------|------|
| 설명 | 선택한 CSV 파일들로 비동기 학습을 시작한다. 파일 검증 후 MLflow run을 생성하고 trainer를 별도 프로세스로 실행, 즉시 202를 반환한다. |
| Method | POST |
| URL | `/api/v1/{platform}/train` |
| 권한 | Public (내부용) |
| 연관 요구사항 | FIT-41 |
| 인증 필요 | 아니오 |

#### 요청

**Path Parameter**

| 이름 | 타입 | 필수 | 설명 |
|------|------|------|------|
| platform | string | Y | `ios` 또는 `android` |

**Request Body**

```json
{
  "files": ["SQUAT_device01_0001.csv", "PUSHUP_device01_0001.csv"],
  "epochs": 200,
  "lr": 0.001
}
```

**Request Body 필드**

| 이름 | 타입 | 필수 | 설명 |
|------|------|------|------|
| files | string[] | Y | 학습에 사용할 파일명 목록. 인덱스에 등록된 파일만 허용(raw 전체가 아닌 선택 학습) |
| epochs | integer | N | 학습 에폭 수 (기본 200) |
| lr | number | N | 학습률 (기본 0.001) |

#### 비즈니스 규칙

- 동일 플랫폼에서 학습이 진행 중이면 409 — 플랫폼당 동시 학습 1개(FIT-41). iOS와 Android 학습은 서로 독립적으로 병행 가능.
- `files` 중 인덱스에 없는 파일이 하나라도 있으면 400.
- 버전은 서버가 자동 채번한다(S3 모델 폴더의 마지막 버전 minor +1, 최초 `v1.0`).
- 학습 완료 시 워커가 산출물을 S3에 업로드하고, 사용한 파일들의 `trainedInVersion`을 이번 버전으로 기록한다.
- 응답의 `jobId`(MLflow run ID)로 이후 진행률을 조회한다.

#### 응답

**성공 응답** — 202 Accepted

```json
{
  "traceId": "0a1b2c3d4e5f60718293a4b5c6d7e8f9",
  "data": {
    "jobId": "a1b2c3d4e5f64789a1b2c3d4e5f64789",
    "experimentId": "1",
    "version": "v1.3",
    "totalEpochs": 200
  }
}
```

**응답 필드**

| 필드 | 타입 | 설명 |
|------|------|------|
| data.jobId | String | MLflow run ID — 상태 조회 키 |
| data.experimentId | String | MLflow experiment ID (`fitset-{platform}`) |
| data.version | String | 이번 학습 산출물 버전 (배포 시 이 값 사용) |
| data.totalEpochs | Integer | 전체 에폭 수 |

**오류 응답**

| HTTP | 상황 | error.message |
|------|------|--------|
| 400 | files에 인덱스에 없는 파일 포함 | `존재하지 않는 파일: [...]` |
| 409 | 동일 플랫폼 학습 진행 중 | `해당 플랫폼 학습이 이미 진행 중입니다.` |
| 400 | platform이 ios/android 외 값 | `platform must be 'ios' or 'android'` |
| 400 | files 필드 누락·타입 오류 | INVALID_REQUEST (검증 오류) |

### 4.2 학습 진행률 조회

#### 기본 정보

| 항목 | 내용 |
|------|------|
| 설명 | MLflow run의 상태와 최신 메트릭(에폭·손실·정확도)을 조회한다. 대시보드가 폴링해 실시간 진행 UI를 그린다. |
| Method | GET |
| URL | `/api/v1/{platform}/train/status` |
| 권한 | Public (내부용) |
| 연관 요구사항 | FIT-41 |
| 인증 필요 | 아니오 |

#### 요청

**Query Parameter**

| 이름 | 타입 | 필수 | 설명 |
|------|------|------|------|
| jobId | string | Y | 학습 시작 응답의 jobId(MLflow run ID) |

#### 비즈니스 규칙

- 메트릭은 워커가 에폭마다 MLflow에 기록한 **최신값**이다. 학습 초기에는 일부 메트릭이 `null`일 수 있다.
- `totalEpochs`는 인메모리 추적값 — 서버 재시작 후 또는 다른(과거) jobId 조회 시 현재 플랫폼 진행 건 기준이라 0 또는 다른 값이 나올 수 있다(§2.2).

#### 응답

**성공 응답** — 200 OK

```json
{
  "traceId": "0a1b2c3d4e5f60718293a4b5c6d7e8f9",
  "data": {
    "status": "running",
    "experimentId": "1",
    "epoch": 42,
    "totalEpochs": 200,
    "trainLoss": 0.3812,
    "valLoss": 0.4523,
    "valAccuracy": 0.8934
  }
}
```

**응답 필드**

| 필드 | 타입 | 설명 |
|------|------|------|
| data.status | String | `running` / `completed` / `failed` |
| data.experimentId | String | MLflow experiment ID |
| data.epoch | Integer | 현재 완료 에폭 (기록 전이면 0) |
| data.totalEpochs | Integer | 전체 에폭 (인메모리 — §2.2 주의) |
| data.trainLoss | Number \| null | 최신 train loss |
| data.valLoss | Number \| null | 최신 validation loss |
| data.valAccuracy | Number \| null | 최신 validation accuracy (0~1) |

**오류 응답**

| HTTP | 상황 | error.message |
|------|------|--------|
| 404 | jobId에 해당하는 run 없음 | `해당 jobId의 작업이 없습니다.` |
| 400 | jobId 쿼리 누락 | INVALID_REQUEST (검증 오류) |

### 4.3 학습 이력 목록 조회

#### 기본 정보

| 항목 | 내용 |
|------|------|
| 설명 | 플랫폼의 최근 학습 run 최대 50개를 파라미터·메트릭과 함께 조회하고, `valAccuracy` 기준 best run을 표시한다. 배포 전 버전 비교용. |
| Method | GET |
| URL | `/api/v1/{platform}/runs` |
| 권한 | Public (내부용) |
| 연관 요구사항 | FIT-43 |
| 인증 필요 | 아니오 |

#### 요청

Path Parameter(`platform`) 외 없음.

#### 비즈니스 규칙

- 데이터 출처는 전적으로 MLflow(별도 DB 없음). 시작 시각 내림차순(최신순) 최대 50개.
- `bestRunId`는 상태가 `FINISHED`이고 `valAccuracy`가 기록된 run 중 최고 정확도 run. 해당 run이 없으면 `null`.
- 학습 이력이 아예 없으면 `data.runs`는 빈 배열(이때 `message`·`bestRunId` 필드는 생략됨).

#### 응답

**성공 응답** — 200 OK

```json
{
  "traceId": "0a1b2c3d4e5f60718293a4b5c6d7e8f9",
  "data": {
    "runs": [
      {
        "runId": "a1b2c3d4e5f64789a1b2c3d4e5f64789",
        "version": "v1.3",
        "status": "FINISHED",
        "startTime": 1783934000000,
        "duration": 312,
        "params": { "epochs": 200, "lr": 0.001, "numFiles": 12 },
        "metrics": {
          "trainLoss": 0.2101,
          "valLoss": 0.3312,
          "valAccuracy": 0.9234,
          "testAccuracy": 0.9101,
          "f1Macro": 0.9052,
          "epoch": 200
        }
      }
    ],
    "bestRunId": "a1b2c3d4e5f64789a1b2c3d4e5f64789"
  }
}
```

**응답 필드**

| 필드 | 타입 | 설명 |
|------|------|------|
| data.runs[].runId | String | MLflow run ID |
| data.runs[].version | String | run 이름 = 모델 버전 (`v1.3`) |
| data.runs[].status | String | MLflow 원문 상태 — `RUNNING` / `FINISHED` / `FAILED` (⚠️ 4.2의 소문자 매핑과 다름) |
| data.runs[].startTime | Integer | 학습 시작 시각 — **epoch milliseconds** |
| data.runs[].duration | Integer \| null | 소요 시간(초). 진행 중이면 null |
| data.runs[].params.epochs | Integer \| null | 요청 에폭 수 |
| data.runs[].params.lr | Number \| null | 학습률 |
| data.runs[].params.numFiles | Integer \| null | 학습에 사용한 파일 수 |
| data.runs[].metrics.* | Number \| null | trainLoss·valLoss·valAccuracy·testAccuracy·f1Macro·epoch — 미기록 시 null |
| data.bestRunId | String \| null | valAccuracy 최고 FINISHED run |

**오류 응답**

| HTTP | 상황 | error.message |
|------|------|--------|
| 400 | platform이 ios/android 외 값 | `platform must be 'ios' or 'android'` |

### 4.4 학습 메트릭 시계열 조회

#### 기본 정보

| 항목 | 내용 |
|------|------|
| 설명 | 특정 run의 메트릭을 step(에폭)별 시계열로 조회한다. 대시보드 학습 곡선 차트용. |
| Method | GET |
| URL | `/api/v1/{platform}/runs/{run_id}/history` |
| 권한 | Public (내부용) |
| 연관 요구사항 | FIT-43 |
| 인증 필요 | 아니오 |

#### 요청

**Path Parameter**

| 이름 | 타입 | 필수 | 설명 |
|------|------|------|------|
| platform | string | Y | `ios` 또는 `android` |
| run_id | string | Y | MLflow run ID |

**Query Parameter**

| 이름 | 타입 | 필수 | 설명 |
|------|------|------|------|
| metric | string | N | 조회할 메트릭 키 (기본 `val_loss`). 가능 값: `train_loss`, `val_loss`, `val_accuracy`, `epoch` 등 워커가 기록한 키 (**snake_case**) |

#### 비즈니스 규칙

- 기록되지 않은 metric 키를 주면 빈 시계열(`history: []`)이 반환된다.
- `run_id`는 4.3 목록 응답에서 받은 `runId`를 그대로 사용한다.

#### 응답

**성공 응답** — 200 OK

```json
{
  "traceId": "0a1b2c3d4e5f60718293a4b5c6d7e8f9",
  "data": {
    "metric": "val_loss",
    "history": [
      { "step": 1, "value": 1.2311 },
      { "step": 2, "value": 0.9812 }
    ]
  }
}
```

**응답 필드**

| 필드 | 타입 | 설명 |
|------|------|------|
| data.metric | String | 조회한 메트릭 키 |
| data.history[].step | Integer | 기록 step (에폭) |
| data.history[].value | Number | 해당 step의 메트릭 값 |

**오류 응답**

| HTTP | 상황 | error.message |
|------|------|--------|
| 400 | platform이 ios/android 외 값 | `platform must be 'ios' or 'android'` |

### 4.5 모델 배포

#### 기본 정보

| 항목 | 내용 |
|------|------|
| 설명 | 지정 버전의 모델을 latest로 기록(S3 latest.json 갱신)한다. 이후 클라이언트가 `/model/latest` 폴링으로 새 모델을 받는다. |
| Method | POST |
| URL | `/api/v1/{platform}/deploy` |
| 권한 | Public (내부용) |
| 연관 요구사항 | FIT-43 |
| 인증 필요 | 아니오 |

#### 요청

**Request Body**

```json
{
  "version": "v1.3"
}
```

**Request Body 필드**

| 이름 | 타입 | 필수 | 설명 |
|------|------|------|------|
| version | string | Y | 배포할 학습 버전 (4.3 목록의 `version` 값) |

#### 비즈니스 규칙

- 해당 버전으로 학습된 MLflow run이 있어야 배포 가능(없으면 404).
- 배포 = `latest.json`에 `{version, modelUrl, deployedAt, mlflowRunId}` 기록. 롤백은 과거 버전으로 다시 deploy하면 된다.
- 기록되는 모델 경로: iOS `s3://fitset-models/ios/{version}/FitSet.mlpackage.zip`, Android `.../android/{version}/FitSet.tflite`.
- 배포 즉시 서버 캐시에 반영되어 다음 `/model/latest` 폴링부터 새 버전이 내려간다.

#### 응답

**성공 응답** — 200 OK

```json
{
  "traceId": "0a1b2c3d4e5f60718293a4b5c6d7e8f9",
  "data": {
    "deployedVersion": "v1.3",
    "platform": "ios",
    "deployedAt": "2026-07-12T07:12:00+00:00"
  }
}
```

**응답 필드**

| 필드 | 타입 | 설명 |
|------|------|------|
| data.deployedVersion | String | 배포된 버전 |
| data.platform | String | 배포 플랫폼 |
| data.deployedAt | String | 배포 시각, ISO 8601 UTC |

**오류 응답**

| HTTP | 상황 | error.message |
|------|------|--------|
| 404 | 플랫폼에 학습 이력 자체가 없음 | `학습 이력이 없습니다.` |
| 404 | 해당 버전의 run 없음 | `버전 {version}의 학습 결과가 없습니다.` |
| 400 | version 필드 누락 | INVALID_REQUEST (검증 오류) |

### 4.6 최신 모델 조회 (앱 폴링)

#### 기본 정보

| 항목 | 내용 |
|------|------|
| 설명 | 현재 배포된 최신 모델 버전·다운로드 URL·클라이언트 최신 여부를 반환한다. 앱이 실행·포그라운드 전환 시 폴링한다. |
| Method | GET |
| URL | `/api/v1/{platform}/model/latest` |
| 권한 | Public (앱) |
| 연관 요구사항 | FIT-45 |
| 인증 필요 | 아니오 |

#### 요청

**Query Parameter**

| 이름 | 타입 | 필수 | 설명 |
|------|------|------|------|
| currentVersion | string | N | 앱이 현재 사용 중인 모델 버전. 전달 시 버전 분포 집계(4.7)에 시각과 함께 기록 |

#### 비즈니스 규칙

- `modelUrl`은 presigned **GET** URL로 **1시간(3600초) 유효**. 앱은 응답 즉시 다운로드해야 하며, URL을 저장해 재사용하지 않는다. HEAD 요청은 서명에 포함되지 않아 403 — GET만 사용.
- `isUpToDate = (currentVersion == latestVersion)` — true면 다운로드 생략. `currentVersion` 미전달 시 항상 false.
- **버전 리포팅**: `currentVersion`이 전달된 폴링은 리포트 시각과 함께 기록되어 분포 집계(4.7)의 재료가 된다. 기기 식별은 하지 않는다.
- iOS는 zip 해제 후 `.mlpackage`를 기기에서 컴파일해 교체, Android는 `.tflite` 파일 교체.
- 서버는 latest.json을 60초 TTL로 캐시하지만 배포는 write-through라 배포 직후에도 최신 값이 내려간다.

#### 응답

**성공 응답** — 200 OK

```json
{
  "traceId": "0a1b2c3d4e5f60718293a4b5c6d7e8f9",
  "data": {
    "latestVersion": "v1.3",
    "modelUrl": "https://fitset-models.s3.ap-northeast-2.amazonaws.com/ios/v1.3/FitSet.mlpackage.zip?X-Amz-...",
    "isUpToDate": false
  }
}
```

**응답 필드**

| 필드 | 타입 | 설명 |
|------|------|------|
| data.latestVersion | String | 배포된 최신 버전 |
| data.modelUrl | String | 모델 다운로드용 presigned GET URL (3600초 유효) |
| data.isUpToDate | Boolean | 앱의 currentVersion이 최신인지 여부 |

**오류 응답**

| HTTP | 상황 | error.message |
|------|------|--------|
| 404 | 배포된 모델이 없음 (최초 배포 전) | `배포된 모델이 없습니다.` |
| 400 | platform이 ios/android 외 값 | `platform must be 'ios' or 'android'` |

### 4.7 모델 버전 분포 조회

#### 기본 정보

| 항목 | 내용 |
|------|------|
| 설명 | `/model/latest` 폴링 시 리포팅된 `currentVersion`을 최근 24시간 윈도우로 집계한 클라이언트 버전 분포를 조회한다. 대시보드 버전 분포 패널용. |
| Method | GET |
| URL | `/api/v1/{platform}/model/version-stats` |
| 권한 | Public (내부용) |
| 연관 요구사항 | FIT-46 |
| 인증 필요 | 아니오 |

#### 요청

Path Parameter(`platform`) 외 없음.

#### 비즈니스 규칙

- **최근 24시간 윈도우 집계** — 리포트를 시각과 함께 쌓아두고 윈도우 안의 것만 센다. 버전을 교체한 기기의 이전 버전 리포트는 24시간이 지나면 만료로 자연히 빠지므로 별도 "빼기"가 필요 없다.
- 기기 식별은 하지 않는다(FIT-46). **호출 횟수 기준 근사치**라 자주 폴링하는 기기가 과대집계될 수 있다 — 정확한 기기 수가 아니라 "어느 버전이 주로 쓰이나"의 지표로 해석할 것.
- 집계는 인메모리 — 서버 재시작 시 초기화되고, 폴링이 들어오며 재구성된다(§2.2).
- `ratio`는 윈도우 내 전체 리포트 대비 비율(소수 둘째 자리 반올림), 리포트 수 내림차순 정렬.

#### 응답

**성공 응답** — 200 OK

```json
{
  "traceId": "0a1b2c3d4e5f60718293a4b5c6d7e8f9",
  "data": {
    "latestVersion": "v1.3",
    "totalReports": 50,
    "stats": [
      { "version": "v1.3", "count": 41, "ratio": 0.82 },
      { "version": "v1.2", "count": 9, "ratio": 0.18 }
    ]
  }
}
```

**응답 필드**

| 필드 | 타입 | 설명 |
|------|------|------|
| data.latestVersion | String \| null | 현재 배포 버전 (미배포면 null) |
| data.totalReports | Integer | 최근 24시간 리포트 수 |
| data.stats[].version | String | 리포팅된 클라이언트 버전 |
| data.stats[].count | Integer | 윈도우 내 해당 버전 리포트 수 |
| data.stats[].ratio | Number | 윈도우 내 전체 리포트 대비 비율 (0~1) |

**오류 응답**

| HTTP | 상황 | error.message |
|------|------|--------|
| 400 | platform이 ios/android 외 값 | `platform must be 'ios' or 'android'` |

## 5. API 목록

| Method | Path | 설명 | 인증 |
|--------|------|------|------|
| POST | `/api/v1/{platform}/train` | 학습 시작 (비동기, 202) | 불필요 |
| GET | `/api/v1/{platform}/train/status?jobId=` | 학습 진행률·메트릭 조회 | 불필요 |
| GET | `/api/v1/{platform}/runs` | 최근 50개 학습 이력 + best run | 불필요 |
| GET | `/api/v1/{platform}/runs/{run_id}/history?metric=` | 메트릭 step별 시계열 | 불필요 |
| POST | `/api/v1/{platform}/deploy` | 지정 버전 배포 (latest 기록) | 불필요 |
| GET | `/api/v1/{platform}/model/latest?currentVersion=` | 최신 모델 조회 + 버전 리포팅 (앱 폴링) | 불필요 |
| GET | `/api/v1/{platform}/model/version-stats` | 클라이언트 버전 분포 조회 (최근 24시간 리포트 기준) | 불필요 |

## 6. 오류 코드 정리

ML 서버는 오류 코드 문자열 체계 없이 **HTTP 상태 + detail 메시지**로 응답한다.

| HTTP | 발생 상황 |
|------|-----------|
| 400 | platform 불일치 / 존재하지 않는 학습 파일 지정 |
| 404 | jobId 없음 / 학습 이력 없음 / 해당 버전 run 없음 / 배포된 모델 없음 |
| 409 | 동일 플랫폼 학습 중복 시작 |
| 400 | 필수 파라미터·필드 누락, 타입 불일치 (INVALID_REQUEST) |
| 500 | MLflow·S3 접근 실패 등 서버 내부 오류 |
