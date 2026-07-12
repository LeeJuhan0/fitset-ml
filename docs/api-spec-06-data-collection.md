# 06. 센서 데이터 수집 API 명세 (Data)

## 1. 문서 정보

| 항목 | 내용 |
|------|------|
| 프로젝트명 | FitSet |
| 문서 범위 | 센서 데이터(IMU CSV) 업로드 및 데이터셋 조회 — ML 서버(fitset-ml-server) |
| API 버전 | v1 |
| Base URL | 환경별 ML 서버 호스트 + `/api/v1/{platform}` |
| 인증 방식 | 없음(MVP — 내부 관리자 대시보드·수집앱 전용) |
| Content-Type | `application/json` (S3 직접 업로드만 `text/csv`) |
| 연관 에픽 | FIT-32 센서 데이터 수집 |
| 최종 수정일 | 2026년 7월 12일 |
| 작성자 | @이주한 |

## 2. 공통 규칙

> ML 서버는 웹 스프링 백엔드(01. API 설계 규약)와 **별도 서버·별도 응답 규약**을 사용한다. 아래 규칙이 본 문서(06)와 07. ML 학습·서빙 명세의 정본이다.

### 2.1 Base URL과 platform 경로 변수

모든 엔드포인트는 `/api/v1/{platform}/...` 형태이며, `{platform}`은 `ios` 또는 `android`만 허용한다. 그 외 값은 `400`으로 거부된다. 데이터셋·모델 버전은 플랫폼별로 완전히 독립 운영된다.

### 2.2 요청 헤더

```
Content-Type: application/json
```

인증 헤더는 없다. (S3 직접 PUT 시에만 `Content-Type: text/csv` — 4.3 참고)

### 2.3 데이터 형식

| 항목 | 규칙 |
|------|------|
| 날짜·시간 | ISO 8601 UTC — `2026-07-12T06:30:00+00:00` |
| JSON 프로퍼티 | camelCase (예외: upload-confirm 요청 바디의 `class_name` — 4.4 참고) |
| 종목 라벨(class) | `CLASSES` 목록의 대문자 스네이크 문자열 (2.5 참고) |
| deviceId | `^[A-Za-z0-9_-]{1,64}$` — 영숫자·`_`·`-`, 1~64자 (S3 키에 포함되므로 형식 제한) |
| 파일명 | **서버가 부여** — `{CLASS}_{deviceId}_{NNNN}.csv` (NNNN = class+deviceId별 4자리 순번) |

### 2.4 업로드 3단계 플로우

클라이언트(수집앱)는 CSV를 서버로 직접 올리지 않고 S3에 직접 업로드한다.

```
① GET /data/presigned-url?class=&deviceId=
      → 서버가 파일명을 채번·예약(uploaded=false)하고 presigned PUT URL 발급 (300초 유효)
② PUT {presignedUrl}  (S3 직접 업로드, Content-Type: text/csv)
③ POST /data/upload-confirm  {filename, class_name}
      → 인덱스의 예약 항목을 uploaded=true로 확정
```

- ③ confirm까지 완료되어야 목록 조회·학습에서 파일이 인식된다(FIT-37).
- ①의 예약은 동시 요청에도 순번이 겹치지 않게 직렬화된다(서버 인프로세스 락 + S3 ETag 낙관적 락).
- 저장 경로: `s3://fitset-dataset/{platform}/raw/{class}/{filename}` — iOS는 `ios/`, Android는 `android/` prefix에만 저장·접근한다.

### 2.5 종목 라벨 (CLASSES)

파일의 `class`는 아래 값만 허용한다. **목록 순서가 곧 모델 출력 클래스 번호**이므로 새 종목은 항상 끝에 추가한다.

`SQUAT`, `PUSHUP`, `DUMBBELL_CURL`, `SIDE_LATERAL_RAISE`, `REST`, `OVERHEAD_PRESS`, `BARBELL_ROW`, `DEADLIFT`, `LAT_PULLDOWN`, `BENCH_PRESS`, `PEC_DECK_FLY`, `HIP_THRUST`, `SEATED_ROW`, `DIPS`

### 2.6 CSV 파일 형식 (참고 — FIT-34)

업로드되는 CSV는 워치가 100Hz로 기록한 IMU 데이터다.

```
timestamp,ax,ay,az,gx,gy,gz,label
```

- 가속도(`ax,ay,az`): CMAccelerometer raw, 단위 g
- 자이로(`gx,gy,gz`): CMDeviceMotion, 단위 rad/s
- `label`: 종목 라벨(CLASSES 값)

## 3. 공통 응답 형식

### 3.1 성공 응답

모든 성공 응답은 아래 envelope을 사용한다.

```json
{
  "success": true,
  "code": "200",
  "message": "파일 목록을 조회했습니다.",
  "data": { }
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| success | Boolean | 항상 `true` |
| code | String | HTTP 상태 코드 문자열 (`"200"`, `"202"`) |
| message | String | 사람이 읽는 처리 결과 메시지 |
| data | Object | 응답 데이터 |

### 3.2 오류 응답

오류는 FastAPI 기본 형식으로 내려간다. (스프링 백엔드의 `error.code` 체계와 다름 — 오류 분기는 **HTTP 상태 코드**로 한다)

```json
{
  "detail": "지원하지 않는 종목: SQUATT. 허용: ['SQUAT', 'PUSHUP', ...]"
}
```

### 3.3 검증 오류 응답 (422)

필수 쿼리 파라미터·바디 필드 누락, 타입 불일치는 FastAPI가 `422`로 응답한다.

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["query", "class"],
      "msg": "Field required",
      "input": null
    }
  ]
}
```

## 4. API 상세 명세

### 4.1 데이터 파일 목록 조회

#### 기본 정보

| 항목 | 내용 |
|------|------|
| 설명 | S3 인덱스(index.json)에 등록된 플랫폼별 수집 파일 목록과 학습 사용 여부를 조회한다. |
| Method | GET |
| URL | `/api/v1/{platform}/data` |
| 권한 | Public (내부용) |
| 연관 요구사항 | FIT-39 |
| 인증 필요 | 아니오 |

#### 요청

**Path Parameter**

| 이름 | 타입 | 필수 | 설명 |
|------|------|------|------|
| platform | string | Y | `ios` 또는 `android` |

**Query Parameter** — 없음

**Request Body** — 없음

#### 비즈니스 규칙

- 인덱스는 예약만 되고 아직 업로드 확정되지 않은 항목(`uploaded=false`)도 포함한다. 학습 화면에서는 `uploaded=true`인 파일만 사용해야 한다.
- `trainedInVersion`이 `null`이면 아직 어떤 학습에도 사용되지 않은 파일이다. 학습 완료 시 워커가 해당 버전 문자열(예: `v1.3`)로 갱신한다.

#### 응답

**성공 응답** — 200 OK

```json
{
  "success": true,
  "code": "200",
  "message": "파일 목록을 조회했습니다.",
  "data": {
    "platform": "ios",
    "files": [
      {
        "filename": "SQUAT_device01_0001.csv",
        "class": "SQUAT",
        "deviceId": "device01",
        "collectedAt": "2026-07-12T06:30:00+00:00",
        "uploaded": true,
        "trainedInVersion": "v1.2"
      }
    ]
  }
}
```

**응답 필드**

| 필드 | 타입 | 설명 |
|------|------|------|
| data.platform | String | 조회한 플랫폼 |
| data.files[] | Array | 등록 파일 목록 (없으면 빈 배열) |
| data.files[].filename | String | 서버가 부여한 파일명 |
| data.files[].class | String | 종목 라벨 |
| data.files[].deviceId | String | 수집 기기 식별자 |
| data.files[].collectedAt | String | 예약(수집) 시각, ISO 8601 UTC |
| data.files[].uploaded | Boolean | 업로드 확정 여부 (3단계 완료 시 true) |
| data.files[].trainedInVersion | String \| null | 학습에 사용된 모델 버전 (미사용 시 null) |

**오류 응답**

| HTTP | 상황 | detail |
|------|------|--------|
| 400 | platform이 ios/android 외 값 | `platform must be 'ios' or 'android'` |

### 4.2 업로드용 Presigned URL 발급

#### 기본 정보

| 항목 | 내용 |
|------|------|
| 설명 | 서버가 인덱스를 보고 파일명을 채번·예약한 뒤, 클라이언트가 S3에 직접 PUT할 수 있는 presigned URL을 발급한다. |
| Method | GET |
| URL | `/api/v1/{platform}/data/presigned-url` |
| 권한 | Public (내부용) |
| 연관 요구사항 | FIT-37 |
| 인증 필요 | 아니오 |

#### 요청

**Path Parameter**

| 이름 | 타입 | 필수 | 설명 |
|------|------|------|------|
| platform | string | Y | `ios` 또는 `android` |

**Query Parameter**

| 이름 | 타입 | 필수 | 설명 |
|------|------|------|------|
| class | string | Y | 종목 라벨 (CLASSES 값만 허용) |
| deviceId | string | Y | 기기 식별자, `^[A-Za-z0-9_-]{1,64}$` |

**Request Body** — 없음

#### 비즈니스 규칙

- 파일명은 클라이언트가 아니라 **서버가** `{CLASS}_{deviceId}_{NNNN}.csv`로 부여한다(중복·충돌 방지, FIT-37).
- 발급과 동시에 인덱스에 예약 항목(`uploaded=false`, `collectedAt`, `trainedInVersion=null`)이 추가된다.
- URL 유효시간은 300초. 만료 후 PUT하면 S3가 403을 반환하므로 재발급받는다(이 경우 새 파일명이 채번된다).

#### 응답

**성공 응답** — 200 OK

```json
{
  "success": true,
  "code": "200",
  "message": "presigned URL을 발급했습니다.",
  "data": {
    "presignedUrl": "https://fitset-dataset.s3.ap-northeast-2.amazonaws.com/ios/raw/SQUAT/SQUAT_device01_0002.csv?X-Amz-...",
    "expiresIn": 300,
    "s3Key": "ios/raw/SQUAT/SQUAT_device01_0002.csv",
    "filename": "SQUAT_device01_0002.csv"
  }
}
```

**응답 필드**

| 필드 | 타입 | 설명 |
|------|------|------|
| data.presignedUrl | String | S3 직접 PUT용 임시 서명 URL |
| data.expiresIn | Integer | URL 유효시간(초) — 300 |
| data.s3Key | String | 업로드될 S3 키 (`{platform}/raw/{class}/{filename}`) |
| data.filename | String | 서버가 부여한 파일명 — **upload-confirm에 그대로 다시 보낸다** |

**오류 응답**

| HTTP | 상황 | detail |
|------|------|--------|
| 400 | class가 CLASSES 외 값 | `지원하지 않는 종목: {값}. 허용: [...]` |
| 400 | deviceId 형식 위반 | `유효하지 않은 deviceId` |
| 400 | platform이 ios/android 외 값 | `platform must be 'ios' or 'android'` |
| 422 | class·deviceId 쿼리 누락 | FastAPI 검증 오류 (3.3) |

### 4.3 (참고) S3 직접 업로드

ML 서버 엔드포인트가 아니라 **발급받은 presigned URL로의 S3 직접 호출**이다.

| 항목 | 내용 |
|------|------|
| Method | PUT |
| URL | 4.2에서 받은 `presignedUrl` 전체 문자열 |
| Header | `Content-Type: text/csv` — **필수** (서명에 포함되어 있어 다른 값이면 403) |
| Body | CSV 파일 바이너리 |
| 성공 | 200 OK (본문 없음, S3 응답) |
| 실패 | 403 (URL 만료·서명 불일치·Content-Type 불일치) — 4.2부터 재시도 |

### 4.4 업로드 확정

#### 기본 정보

| 항목 | 내용 |
|------|------|
| 설명 | S3 PUT 완료 후, presigned 단계에서 예약된 인덱스 항목을 `uploaded=true`로 확정한다. |
| Method | POST |
| URL | `/api/v1/{platform}/data/upload-confirm` |
| 권한 | Public (내부용) |
| 연관 요구사항 | FIT-37 |
| 인증 필요 | 아니오 |

#### 요청

**Path Parameter**

| 이름 | 타입 | 필수 | 설명 |
|------|------|------|------|
| platform | string | Y | `ios` 또는 `android` |

**Request Body**

```json
{
  "filename": "SQUAT_device01_0002.csv",
  "class_name": "SQUAT"
}
```

**Request Body 필드**

| 이름 | 타입 | 필수 | 설명 |
|------|------|------|------|
| filename | string | Y | 4.2에서 서버가 부여한 파일명 그대로 |
| class_name | string | Y | 종목 라벨 (CLASSES 값). ⚠️ 키 이름이 camelCase가 아닌 `class_name`(snake_case) |

#### 비즈니스 규칙

- 4.2에서 예약된 filename만 확정 가능하다. 예약 없이 호출하면 404.
- 멱등: 이미 확정된 파일에 다시 호출해도 200으로 성공한다.
- confirm 완료 후에야 목록 조회(uploaded=true)·학습에서 파일이 인식된다.

#### 응답

**성공 응답** — 200 OK

```json
{
  "success": true,
  "code": "200",
  "message": "업로드를 확정했습니다.",
  "data": {
    "filename": "SQUAT_device01_0002.csv",
    "class": "SQUAT"
  }
}
```

**응답 필드**

| 필드 | 타입 | 설명 |
|------|------|------|
| data.filename | String | 확정된 파일명 |
| data.class | String | 종목 라벨 (응답은 `class` 키 사용) |

**오류 응답**

| HTTP | 상황 | detail |
|------|------|--------|
| 400 | class_name이 CLASSES 외 값 | `지원하지 않는 종목: {값}` |
| 404 | 예약된 filename이 인덱스에 없음 | `예약된 파일을 찾을 수 없습니다.` |
| 400 | platform이 ios/android 외 값 | `platform must be 'ios' or 'android'` |
| 422 | filename·class_name 필드 누락 | FastAPI 검증 오류 (3.3) |

## 5. API 목록

| Method | Path | 설명 | 인증 |
|--------|------|------|------|
| GET | `/api/v1/{platform}/data` | 등록 파일 목록·학습 사용 여부 조회 | 불필요 |
| GET | `/api/v1/{platform}/data/presigned-url` | 파일명 채번·예약 + presigned PUT URL 발급(300초) | 불필요 |
| PUT | `{presignedUrl}` (S3) | CSV 직접 업로드 (`Content-Type: text/csv`) | presigned 서명 |
| POST | `/api/v1/{platform}/data/upload-confirm` | 예약 항목 업로드 확정(`uploaded=true`) | 불필요 |

## 6. 오류 코드 정리

ML 서버는 오류 코드 문자열 체계 없이 **HTTP 상태 + detail 메시지**로 응답한다.

| HTTP | 발생 상황 |
|------|-----------|
| 400 | platform 불일치 / 지원하지 않는 종목 / deviceId 형식 위반 |
| 404 | 예약되지 않은 파일 confirm 시도 |
| 422 | 필수 파라미터·필드 누락, 타입 불일치 (FastAPI 검증) |
| 500 | S3 접근 실패 등 서버 내부 오류 |
