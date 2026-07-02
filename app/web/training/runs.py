# ─────────────────────────────────────────────────────────────────────────────
# 학습 이력 도메인 API — main.py가 runs_router로 등록.
# 엔드포인트: GET /runs(목록+best), GET /runs/{run_id}/history(메트릭 시계열)
# 데이터 출처는 전적으로 MLflow(별도 DB 없음).
# ─────────────────────────────────────────────────────────────────────────────
import mlflow
from fastapi import APIRouter, Depends

from app.web.deps import validate_platform
from app.core.config import settings

router = APIRouter()


@router.get("/api/v1/{platform}/runs")
def list_runs(platform: str = Depends(validate_platform)):
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = mlflow.MlflowClient()

    exp = client.get_experiment_by_name(f"fitset-{platform}")   # 플랫폼 experiment
    if not exp:
        return {"success": True, "code": "200", "data": {"runs": []}}   # 학습 이력 없음

    # search_runs(experiment_ids, order_by, max_results) : run들을 검색.
    raw = client.search_runs(
        experiment_ids=[exp.experiment_id],
        order_by=["start_time DESC"],   # 최신순
        max_results=50,                 # 최근 50개
    )

    runs = []
    for r in raw:                       # 각 run을 화면용 dict로 가공
        p = r.data.params               # 학습 파라미터(문자열로 저장됨)
        m = r.data.metrics              # 메트릭(float)
        start_ms = r.info.start_time     # 시작 시각(ms epoch)
        end_ms   = r.info.end_time       # 종료 시각(없으면 None)
        duration = round((end_ms - start_ms) / 1000) if end_ms else None   # 소요(초)

        runs.append({
            "runId":        r.info.run_id,
            "version":      r.info.run_name,
            "status":       r.info.status,
            "startTime":    start_ms,
            "duration":     duration,
            "params": {     # 문자열로 저장된 파라미터를 숫자로 복원
                "epochs":     int(p["epochs"])     if "epochs"     in p else None,
                "lr":         float(p["lr"])        if "lr"         in p else None,
                "numFiles":   len(__import__("json").loads(p["files"])) if "files" in p else None,  # files JSON 길이
            },
            "metrics": {
                "trainLoss":   m.get("train_loss"),
                "valLoss":     m.get("val_loss"),
                "valAccuracy": m.get("val_accuracy"),
                "testAccuracy":m.get("test_accuracy"),
                "f1Macro":     m.get("f1_macro"),
                "epoch":       int(m.get("epoch", 0)),
            },
        })

    # val_accuracy 기준 best run 표시
    finished = [r for r in runs if r["status"] == "FINISHED" and r["metrics"]["valAccuracy"] is not None]
    best_id = max(finished, key=lambda r: r["metrics"]["valAccuracy"])["runId"] if finished else None   # 최고 정확도 run

    return {
        "success": True,
        "code":    "200",
        "data":    {"runs": runs, "bestRunId": best_id},
    }


@router.get("/api/v1/{platform}/runs/{run_id}/history")
def run_metric_history(run_id: str, metric: str = "val_loss", platform: str = Depends(validate_platform)):
    # run_id: 경로 변수,  metric: 쿼리 ?metric=(기본 val_loss),  platform: 경로 검증값
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = mlflow.MlflowClient()

    # get_metric_history(run_id, key) : 그 메트릭의 step별 기록 전체를 반환.
    history = client.get_metric_history(run_id, metric)
    return {
        "success": True,
        "code":    "200",
        "data": {
            "metric":  metric,
            "history": [{"step": h.step, "value": h.value} for h in history],   # (step, value) 시계열
        },
    }
