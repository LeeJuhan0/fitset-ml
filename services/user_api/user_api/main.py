# ─────────────────────────────────────────────────────────────────────────────
# user_api — 유저 트래픽 전용 서비스. 앱이 직접 호출하는 3개 엔드포인트만 노출한다:
#   GET  /ml/v1/{platform}/data/presigned-url   (Bearer JWT)
#   POST /ml/v1/{platform}/data/upload-confirm  (Bearer JWT)
#   GET  /ml/v1/{platform}/model/latest         (Bearer JWT)
# 경로 정본은 /ml/v1 — api-stage.* 단일 도메인에서 백엔드 /api/*와 충돌을 피한다(2026-08-27).
# 앱 클라 미출시라 구 /api/v1 병행 없이 클린 시작한다.
# 어드민 라우터·대시보드·mlflow 프록시·학습 worker는 이 서비스에 실리지 않는다 —
# 인증 계층(JWT)이 곧 모듈 경계다. 뼈대(로깅·에러 봉투·미들웨어)는 bootstrap이 정본.
# 실행: uvicorn user_api.main:app  (PYTHONPATH: libs/common, services/user_api)
# ─────────────────────────────────────────────────────────────────────────────
from app.bootstrap import ERROR_DOC, create_base_app
from app.data.router import router as data_router          # 유저: presigned-url·upload-confirm
from app.deployment.router import router as deploy_router  # 유저: model/latest

app = create_base_app("FitSet ML User API")   # 정적 마운트가 없으므로 protect_static 불필요

app.include_router(data_router, prefix="/ml/v1", responses=ERROR_DOC)
app.include_router(deploy_router, prefix="/ml/v1", responses=ERROR_DOC)
