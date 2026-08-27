# ─────────────────────────────────────────────────────────────────────────────
# admin_api — 운영 전용 서비스(팀 내부). Basic 인증 뒤에서 대시보드·학습·배포·승격을 담당:
#   /api/v1/*       (데이터 목록·통계·업로드 승격, 학습·이력, 배포·버전 분포·latest 알리아스)
#   /mlflow/*       (MLflow UI 역프록시 — 대상은 env MLFLOW_PROXY_TARGET)
#   /               (정적 대시보드 — 정적 Basic 가드 포함, protect_static=True)
# 경로 정본은 /api/v1 — 어드민 호스트(admin-stage.*)가 경계라 경로에 admin을 중복하지
# 않는다(2026-08-27). 유저 서비스는 api-stage.* 호스트의 /ml/v1 — 호스트+prefix가 다 다르다.
# 학습 worker(subprocess)는 이 서비스 이미지에 함께 실린다.
# 실행: uvicorn admin_api.main:app  (PYTHONPATH: libs/common, services/admin_api)
# ─────────────────────────────────────────────────────────────────────────────
from pathlib import Path

from fastapi.staticfiles import StaticFiles                # 정적 파일(대시보드) 서빙용

from app.bootstrap import ERROR_DOC, create_base_app
from app.data.router import admin_router as data_admin_router          # 어드민: 목록·통계·업로드 승격
from app.training.router import router as train_router                 # 어드민: train·runs 전체
from app.deployment.router import admin_router as deploy_admin_router  # 어드민: deploy·version-stats·latest 알리아스
from app.mlflow_proxy import router as mlflow_proxy_router             # /mlflow/* — Basic 인증 뒤 단건 중계

# 정적 경로는 CWD가 아니라 이 파일 기준 — 컨테이너·로컬 어디서 띄워도 같은 위치를 본다
_STATIC_DIR = Path(__file__).resolve().parent / "static"

app = create_base_app("FitSet ML Admin API", protect_static=True)

app.include_router(data_admin_router, prefix="/api/v1", responses=ERROR_DOC)
app.include_router(train_router, prefix="/api/v1", responses=ERROR_DOC)
app.include_router(deploy_admin_router, prefix="/api/v1", responses=ERROR_DOC)
app.include_router(mlflow_proxy_router)   # 문서 비노출, "/" 정적 마운트보다 먼저

# "/"에 마운트하므로 위 API 라우트들보다 "나중에" 둬야 API가 가려지지 않는다.
app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")
