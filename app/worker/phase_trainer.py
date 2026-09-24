import argparse
import json
import os
import tempfile
import traceback

import mlflow
import numpy as np
import torch
import torch.nn as nn

from app.core import db, s3
from app.core.config import settings
from app.exercises.repository import folder_for
from app.data.repository import dataset_locations
from app.phase.repository import fail_phase_model, finish_phase_model
from app.worker import phase_algo as algo


async def _with_session(fn, *args, **kwargs):
    """워커용, 세션 하나 열어 repository 코루틴 실행"""
    async with db.session() as s:
        return await fn(s, *args, **kwargs)
from app.worker.model_def import FitSetModel
from app.worker.preprocess import CHANNELS, load_table

NUM_CLASSES = 3
CLASS_NAMES = ["down", "up", "pause"]
INFER_STRIDE = 10
VAL_FRAC = 0.2
BATCH = 64
SEED = 0
MODEL_NAME = "FitSetPhase"


def load_files(platform: str, filenames: list[str], workdir: str) -> list[tuple[str, np.ndarray, np.ndarray]]:
    """dataset_files parquet 다운로드, (이름, 신호, phase) 목록"""
    out = []
    locations = db.run(_with_session(dataset_locations, platform, filenames))
    for name, (bucket, key) in locations.items():
        local = os.path.join(workdir, name)
        s3.download_object(bucket, key, local)
        df = load_table(local)
        out.append((name, df[CHANNELS].to_numpy(dtype=np.float32), df["phase"].to_numpy(dtype=int)))
    return out


def windows_of(files, window: int, stride: int) -> tuple[np.ndarray, np.ndarray]:
    """파일 묶음 → 윈도우 배열"""
    xs, ys = zip(*[algo.make_windows(x, y, window, stride) for _, x, y in files])
    return np.concatenate(xs), np.concatenate(ys)


def train(x_tr: np.ndarray, y_tr: np.ndarray, epochs: int, lr: float, device) -> tuple[FitSetModel, list[float]]:
    """클래스 가중 CE, Adam, 에폭별 train loss"""
    torch.manual_seed(SEED)
    model = FitSetModel(num_classes=NUM_CLASSES).to(device)
    counts = np.bincount(y_tr, minlength=NUM_CLASSES).astype(np.float32)
    weights = torch.tensor(counts.sum() / (NUM_CLASSES * np.maximum(counts, 1)), dtype=torch.float32).to(device)
    criterion = nn.CrossEntropyLoss(weight=weights)
    optim = torch.optim.Adam(model.parameters(), lr=lr)
    xt, yt = torch.from_numpy(x_tr), torch.from_numpy(y_tr)
    losses = []
    for epoch in range(1, epochs + 1):
        model.train()
        perm = torch.randperm(len(xt))
        total = 0.0
        for i in range(0, len(perm), BATCH):
            idx = perm[i:i + BATCH]
            xb, yb = xt[idx].to(device), yt[idx].to(device)
            optim.zero_grad()
            loss = criterion(model(xb), yb)
            loss.backward()
            optim.step()
            total += loss.item() * len(idx)
        losses.append(round(total / len(xt), 4))
        mlflow.log_metric("train_loss", losses[-1], step=epoch)
    return model, losses


def infer_sequence(model, x: np.ndarray, mean, std, window: int, device) -> list[int]:
    """워치와 같은 추론, 윈도우를 INFER_STRIDE 씩 밀며 argmax"""
    starts = range(0, len(x) - window + 1, INFER_STRIDE)
    xs = np.array([x[s:s + window] for s in starts], dtype=np.float32)
    if len(xs) == 0:
        return []
    with torch.no_grad():
        logits = model(torch.from_numpy((xs - mean) / std).to(device))
    return logits.argmax(dim=1).cpu().tolist()


def evaluate(model, files, mean, std, window: int, device) -> dict:
    """윈도우 정확도, 클래스별 F1, 파일별 렙 수 오차"""
    correct = total = 0
    tp = np.zeros(NUM_CLASSES); fp = np.zeros(NUM_CLASSES); fn = np.zeros(NUM_CLASSES)
    per_file = {}
    for name, x, y in files:
        xs, ys = algo.make_windows(x, y, window, INFER_STRIDE)
        if len(xs) == 0:
            continue
        with torch.no_grad():
            pred = model(torch.from_numpy((xs - mean) / std).to(device)).argmax(dim=1).cpu().numpy()
        correct += int((pred == ys).sum()); total += len(ys)
        for c in range(NUM_CLASSES):
            tp[c] += int(((pred == c) & (ys == c)).sum())
            fp[c] += int(((pred == c) & (ys != c)).sum())
            fn[c] += int(((pred != c) & (ys == c)).sum())
        gt = algo.count_reps([int(v) for v in y if v >= 0])
        pr = algo.count_reps(infer_sequence(model, x, mean, std, window, device))
        per_file[name] = {"label_count": gt, "model_count": pr}
    f1 = 2 * tp / np.maximum(2 * tp + fp + fn, 1)
    errs = [abs(v["label_count"] - v["model_count"]) for v in per_file.values()]
    return {
        "acc": round(correct / max(total, 1), 4),
        "f1": {CLASS_NAMES[i]: round(float(v), 3) for i, v in enumerate(f1)},
        "macro_f1": round(float(f1.mean()), 4),
        "count_mae": round(float(np.mean(errs)), 2) if errs else None,
        "per_file": per_file,
    }


def export_and_upload(model, mean, std, window: int, platform: str, class_name: str, version: str, meta: dict) -> dict:
    """pt, onnx, mlpackage.zip, meta.json 업로드, 키 dict"""
    from app.worker.convert import to_mlpackage, to_onnx

    bucket = settings.phase_models_bucket
    prefix = f"{platform}/{db.run(_with_session(folder_for, class_name))}/{version}"
    keys = {}
    with tempfile.TemporaryDirectory() as out:
        pt = os.path.join(out, f"{MODEL_NAME}.pt")
        torch.save(model.state_dict(), pt)
        keys["pt_key"] = f"{prefix}/{MODEL_NAME}.pt"
        s3.upload_object(bucket, keys["pt_key"], pt, "application/octet-stream")

        onnx_path = os.path.join(out, f"{MODEL_NAME}.onnx")
        to_onnx(model, mean.tolist(), std.tolist(), onnx_path, window=window)
        keys["onnx_key"] = f"{prefix}/{MODEL_NAME}.onnx"
        s3.upload_object(bucket, keys["onnx_key"], onnx_path, "application/octet-stream")

        zip_path = to_mlpackage(model, mean.tolist(), std.tolist(), os.path.join(out, f"{MODEL_NAME}.mlpackage"), window=window)
        keys["mlpackage_key"] = f"{prefix}/{MODEL_NAME}.mlpackage.zip"
        s3.upload_object(bucket, keys["mlpackage_key"], zip_path, "application/zip")

        meta_path = os.path.join(out, "meta.json")
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)
        keys["meta_key"] = f"{prefix}/meta.json"
        s3.upload_object(bucket, keys["meta_key"], meta_path, "application/json")
        mlflow.log_artifact(meta_path)
    return keys


def run(platform: str, class_name: str, model_id: int, version: str, filenames: list[str], window: int, stride: int, epochs: int, lr: float) -> None:
    """다운로드, 검증 분할 학습, 전체 재학습, 내보내기, 목록 갱신"""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    try:
        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        mlflow.set_experiment(f"fitset-phase-{platform}")
        with mlflow.start_run(run_name=f"{class_name}-{version}") as run, tempfile.TemporaryDirectory() as workdir:
            mlflow.log_params({"class": class_name, "window": window, "stride": stride, "epochs": epochs, "lr": lr, "num_files": len(filenames)})
            files = load_files(platform, filenames, workdir)
            tr_files = [(n, x[:int(len(x) * (1 - VAL_FRAC))], y[:int(len(x) * (1 - VAL_FRAC))]) for n, x, y in files]
            va_files = [(n, x[int(len(x) * (1 - VAL_FRAC)):], y[int(len(x) * (1 - VAL_FRAC)):]) for n, x, y in files]

            x_tr, y_tr = windows_of(tr_files, window, stride)
            mean = x_tr.reshape(-1, 6).mean(axis=0).astype(np.float32)
            std = x_tr.reshape(-1, 6).std(axis=0).astype(np.float32) + 1e-6
            model, _ = train((x_tr - mean) / std, y_tr, epochs, lr, device)
            model.eval()
            val = evaluate(model, va_files, mean, std, window, device)
            mlflow.log_metrics({"val_acc": val["acc"], "val_macro_f1": val["macro_f1"], **({"val_count_mae": val["count_mae"]} if val["count_mae"] is not None else {})})

            x_all, y_all = windows_of(files, window, stride)
            mean = x_all.reshape(-1, 6).mean(axis=0).astype(np.float32)
            std = x_all.reshape(-1, 6).std(axis=0).astype(np.float32) + 1e-6
            model, _ = train((x_all - mean) / std, y_all, epochs, lr, device)
            model.cpu().eval()
            final = evaluate(model, files, mean, std, window, "cpu")
            metrics = {"val": val, "final": final, "label_counts": np.bincount(y_all, minlength=NUM_CLASSES).tolist()}

            meta = {"platform": platform, "class": class_name, "version": version, "classes": CLASS_NAMES,
                    "input_shape": [1, window, 6], "window": window, "train_stride": stride, "infer_stride": INFER_STRIDE,
                    "mean": mean.tolist(), "std": std.tolist(), "trained_files": filenames, "metrics": metrics,
                    "mlflow_run_id": run.info.run_id}
            keys = export_and_upload(model, mean, std, window, platform, class_name, version, meta)
            db.run(_with_session(finish_phase_model, model_id, keys=keys, metrics=metrics, mlflow_run_id=run.info.run_id))
            print(f"DONE {class_name} {version} {json.dumps(final)}", flush=True)
    except Exception as e:
        db.run(_with_session(fail_phase_model, model_id, f"{type(e).__name__}: {e}"[-500:]))
        print(f"FAIL {class_name} {version}\n{traceback.format_exc()}", flush=True)


def main():
    """CLI 인자 파싱, 학습 실행"""
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", required=True)
    ap.add_argument("--class", dest="class_name", required=True)
    ap.add_argument("--model-id", type=int, required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--files", required=True)
    ap.add_argument("--window", type=int, default=50)
    ap.add_argument("--stride", type=int, default=5)
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--lr", type=float, default=1e-3)
    a = ap.parse_args()
    run(a.platform, a.class_name, a.model_id, a.version, json.loads(a.files), a.window, a.stride, a.epochs, a.lr)


if __name__ == "__main__":
    main()
