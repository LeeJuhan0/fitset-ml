# FitSet ML Server — 코드 아키텍처

**단일 모듈 app/ 안에서 도메인별 수직 슬라이스(package by feature) + 슬라이스 내부 계층형(router→service→utils→repository) + 런타임 분리(web/worker)** 구조입니다. 2026-09-22 에 libs/common + services/* 멀티모듈을 걷어냈다. 관리자 전용이라 웹서버 컨테이너 하나와 MLflow 컨테이너 하나만 뜬다.

최상위는 도메인(data·training·deployment)으로 나누고, 각 도메인 안에서 층을 나눕니다. 학습 실행은 별도 프로세스 런타임인 `worker/`로 분리합니다.

```
app/
├── main.py              # Composition Root — CORS·헬스체크·예외 핸들러·미들웨어·라우터·정적 마운트 (entrypoint: app.main:app)
├── static/index.html    # 정적 대시보드 (main 이 "/" 에 마운트)
├── deps.py              # 공통 의존성 (validate_platform, DbSessionDep — AsyncSession, 요청 하나가 트랜잭션 하나, 응답 전 commit·예외 시 rollback)
│
├── core/                # ── 공유 인프라 (도메인·worker 공통) ──
│   ├── config.py        #    설정(settings), PLATFORMS, CLASSES, PHASE_CLASSES
│   ├── schemas.py       #    공통 응답 봉투(ApiResponse)·CamelModel(SQLModel 비테이블, camelCase) — 전 도메인 response_model의 기반
│   ├── db.py            #    비동기 엔진(create_async_engine)·세션 팩토리(async_sessionmaker)·테이블 생성, 워커용 run()
│   ├── exceptions.py    #    횡단 예외 (플랫폼 검증, 관리자 인증) — 각 예외가 status_code·detail 을 직접 정한다
│   ├── exception_register.py  # 전역 예외 핸들러 3종, 실패 봉투 조립
│   ├── logging.py       #    traceId 로깅 필터 + trace 미들웨어·액세스 로그
│   ├── utils.py         #    순수 헬퍼 (utcnow, wire_alias, parse_iso)
│   ├── models.py        #    도메인 공유 기준 테이블(SQLModel) — platforms·devices·exercises + WIRE(camelCase) 규약·ensure_*·find_exercise 헬퍼
│   └── s3.py            #    S3 클라이언트·키 조립·객체 업로드/복사/삭제·presigned URL
│
├── data/                # ── 도메인 ① 센서 데이터 수집 ──
├── training/            # ── 도메인 ② 모델 학습·이력 ──
├── deployment/          # ── 도메인 ③ 배포·모델 서빙 ──
├── phase/               # ── 도메인 ④ 수집앱 IMU+영상 업로드·구간 라벨링·렙카운팅 모델 ──
├── exercises/           # ── 도메인 ⑤ 운동 종목 마스터 조회·시드 (엔티티는 core.models.Exercise) ──
│   │                    #    도메인 모두 같은 내부 계층:
│   ├── router.py        #    API(controller) — *Request DTO 를 풀어 기본 값으로 service 에 넘기고, 받은 *Response 를 ApiResponse 로 포장
│   ├── service.py       #    유스케이스 조율 (repository·utils 조립), 실패는 exceptions 를 가드 절에서 raise, 기본 값을 받고 *Response 를 필드 이름으로 생성해 반환 (camelCase 는 모름)
│   ├── utils.py         #    순수 계산 (I/O 없음 — 파일명·버전 채번, 라벨링·승격 가능 판정, 집계 윈도우 등)
│   ├── enums.py         #    상태 Enum (phase: CollectStatus·PhaseModelStatus·ModelFormat), hybrid_property 와 도메인 상수가 참조
│   ├── exceptions.py    #    도메인 예외 — HTTPException 하위, __init__ 에서 status_code·detail 명시
│   ├── models.py        #    엔티티(SQLModel table=True) + Read 모델 — data: dataset_files, phase: collect_files·phase_labels·phase_models
│   ├── repository.py    #    저장소 접근 (AsyncSession 을 인자로 받아 core.s3 와 함께 도메인별 read/write)
│   └── schemas.py       #    요청·응답 DTO (SQLModel 비테이블, CamelModel) — 들어오는 바디·쿼리는 *Request, 나가는 응답은 *Response, 응답 안의 항목 모델은 이름만 (SkippedFile 등)
│
└── worker/              # ── 별도 프로세스 런타임 (학습·라벨링 서브프로세스) ──
    ├── trainer.py       #    학습 엔트리포인트 (training service가 subprocess로 실행)
    ├── model_def.py     #    모델 정의
    ├── preprocess.py    #    전처리
    ├── convert.py       #    모델 변환 (tflite / mlpackage)
    ├── phase_algo.py    #    관절 각도 → phase(0·1·2) 순수 계산, 윈도우·렙 수 규칙 (numpy·scipy)
    ├── phase_labeler.py #    MediaPipe Pose 추출 + parquet 저장 + S3 이동 + 목록 갱신 (phase service가 subprocess로 실행)
    └── phase_trainer.py #    종목별 렙카운팅 모델 학습 + pt·onnx·mlpackage 업로드 (phase service가 subprocess로 실행)

mlflow/Dockerfile        # MLflow 추적 서버 이미지 (별도 컨테이너)
```

| 층 | 역할 | 아는 것 / 모르는 것 |
|------|------|----------|
| `router` | HTTP 라우팅·형식 검증, *Request 풀기 | HTTP와 DTO를 안다 / 업무 규칙 모름 |
| `service` | 유스케이스 순서 조율, *Response 생성 | 흐름을 안다 / HTTP·SQL·*Request·camelCase 모름 (예외는 HTTPException 하위 도메인 예외로 던짐) |
| `utils` | 순수 계산·불변식 | 규칙만 안다 / I/O 없음 |
| `exceptions` | 도메인 예외(HTTPException 하위), 클래스마다 status_code·detail 명시 | 상태코드·메시지 / service 가 가드 절에서 던진다 |
| `repository` | 저장소 read/write, 세션은 첫 인자로 받고 스스로 열지 않는다 | DB(SQLModel)·S3·MLflow를 안다 / 규칙 모름 |
| `core` | 도메인들이 공유하는 저수준 인프라 | DB 세션·엔티티, boto3 클라이언트 |

> 구조 레퍼런스: [Netflix Dispatch](https://github.com/Netflix/dispatch) — 도메인 폴더마다 views(router)·service·models를 두는 FastAPI 도메인 슬라이싱 구조를 참고했다.

## 핵심 설계 포인트

1. **도메인 슬라이싱** — 기능 하나 = 폴더 하나. 새 도메인(예: 추천)이 생기면 같은 내부 계층의 폴더를 추가한다.
2. **런타임 분리(web/worker)** — API 프로세스와 `worker`(학습)는 별개의 프로세스이며 `core`를 공유한다. 의존 방향은 도메인→`core`, `worker`→`core` + 도메인의 `models`·`repository`(영속 계층)까지이고, worker 는 `router`·`service` 를 import 하지 않으며 web 쪽은 `worker`를 import하지 않는다(`-m app.worker.trainer`로 spawn만 함). 엔티티가 도메인 안에 있으므로 워커용 조회·갱신(data.repository 의 mark_trained, phase.repository 의 finish_label)도 도메인 repository 에 둔다.
3. **Producer–Worker (Job Offloading)** — 학습은 `subprocess.Popen`으로 `app.worker.trainer`를 별도 프로세스로 실행하고, API는 즉시 `202 Accepted`를 반환. (Celery/RQ를 서브프로세스로 단순화한 형태.)
4. **상태 외부화** — 학습 추적/메트릭은 **MLflow**, 파일 목록은 **DB(sqlite 볼륨)**, 배포 포인터(latest.json)는 **S3** 에 저장. 2026-09-22 에 index.json ETag 락 엔진을 DB 로 대체했다. (단, training의 `_running`·deployment의 `_reports` 는 인메모리라 서버 재시작 시 초기화됨.)

> **폴더는 `web`/`worker`로 분리하되, 이미지는 하나입니다.** 향후 사용자 데이터가 늘어 학습 부하가 커지면 워커를 별도 서비스로 떼어 독립 스케일업할 수 있도록 경계를 미리 그어 두었고, MVP 단계에서는 단일 이미지·단일 인스턴스에 web·worker를 함께 배포합니다(워커는 web 컨테이너 안에서 `Popen`으로 실행). 분리 트리거(상시 GPU·동시 학습·장애 격리 필요)가 실제로 오면 그때 requirements·이미지·큐를 분리합니다.

5. **요청 단위 트랜잭션(비동기)** — 라우터는 `async def` 이고 `session: DbSessionDep`(deps.py, AsyncSession)으로 세션을 받아 `await service(...)` → `await repository(...)` 로 넘긴다. 쿼리는 `(await s.exec(stmt)).all()`. 요청 안에서 repository 를 몇 번 부르든 응답 직전에 한 번 commit 되고 예외가 나면 전부 rollback 된다. 워커를 spawn 하는 서비스(start_labeling, start_phase_training)는 spawn 직전에 `s.commit()` 을 불러 자식 프로세스가 커밋된 행을 보게 한다. 워커·스크립트는 요청이 없으므로 `db.run(coro)` 로 이벤트 루프를 열고 `async with db.session()` 을 직접 쓴다. boto3·pandas 같은 동기 작업은 서비스에서 `asyncio.to_thread` 로 감싼다.

6. **이벤트 루프는 요청 처리만** — async 라우터·서비스는 DB(AsyncSession)만 직접 await 한다. S3 다운로드·복사·업로드, pandas 파싱, MLflow 클라이언트 호출, 매핑 JSON 다운로드는 `asyncio.to_thread` 로 기본 스레드풀에 넘긴다. presigned URL 서명은 로컬 HMAC 계산이라 루프에서 바로 한다. MLflow 조회만 하는 training·deployment 라우터는 `def` 라 FastAPI 가 스레드풀에서 돌린다. 분류 학습·구간 라벨링·렙카운팅 학습은 CPU 바운드라 `subprocess.Popen` 별도 프로세스이고, 라우터는 202 로 바로 돌아온다.
