import mlflow
from fastapi import APIRouter, Depends

from app.api.deps import validate_platform
from app.core.config import settings

router = APIRouter()


@router.get("/api/v1/{platform}/runs")
def list_runs(platform: str = Depends(validate_platform)):
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = mlflow.MlflowClient()

    exp = client.get_experiment_by_name(f"fitset-{platform}")
    if not exp:
        return {"success": True, "code": "200", "data": {"runs": []}}

    raw = client.search_runs(
        experiment_ids=[exp.experiment_id],
        order_by=["start_time DESC"],
        max_results=50,
    )

    runs = []
    for r in raw:
        p = r.data.params
        m = r.data.metrics
        start_ms = r.info.start_time
        end_ms   = r.info.end_time
        duration = round((end_ms - start_ms) / 1000) if end_ms else None

        runs.append({
            "runId":        r.info.run_id,
            "version":      r.info.run_name,
            "status":       r.info.status,
            "startTime":    start_ms,
            "duration":     duration,
            "params": {
                "epochs":     int(p["epochs"])     if "epochs"     in p else None,
                "lr":         float(p["lr"])        if "lr"         in p else None,
                "numFiles":   len(__import__("json").loads(p["files"])) if "files" in p else None,
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
    best_id = max(finished, key=lambda r: r["metrics"]["valAccuracy"])["runId"] if finished else None

    return {
        "success": True,
        "code":    "200",
        "data":    {"runs": runs, "bestRunId": best_id},
    }


@router.get("/api/v1/{platform}/runs/{run_id}/history")
def run_metric_history(run_id: str, metric: str = "val_loss", platform: str = Depends(validate_platform)):
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = mlflow.MlflowClient()

    history = client.get_metric_history(run_id, metric)
    return {
        "success": True,
        "code":    "200",
        "data": {
            "metric":  metric,
            "history": [{"step": h.step, "value": h.value} for h in history],
        },
    }
