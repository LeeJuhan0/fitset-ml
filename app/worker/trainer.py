import argparse
import json
import os
import random
import tempfile
from pathlib import Path

import mlflow
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from app.core import db


async def _with_session(fn, *args):
    """세션 하나 열어 repository 코루틴 실행"""
    async with db.session() as s:
        return await fn(s, *args)
from app.core.config import CLASSES, settings
from app.core.s3 import download_object, upload_model_artifact
from app.data.repository import dataset_locations, mark_trained
from app.worker.model_def import FitSetModel
from app.worker.preprocess import STRIDE, WINDOW, compute_stats, load_csv, normalize, sliding_window


def run(platform: str, files: list[str], epochs: int, lr: float, run_id: str, version: str):
    """분류 학습 파이프라인, 다운로드 윈도잉 학습 평가 변환 업로드"""
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)

    with mlflow.start_run(run_id=run_id):
        mlflow.log_params({
            "platform": platform,
            "epochs": epochs,
            "lr": lr,
            "batch_size": 64,
            "optimizer": "Adam",
            "num_files": len(files),
            "files": json.dumps(files),
            "num_classes": len(CLASSES),
            "arch_input_window": 200,
            "arch_input_channels": 6,
            "arch_cnn_filters": 256,
            "arch_cnn_kernel": 5,
            "arch_cnn_stride": 1,
            "arch_cnn_padding": 2,
            "arch_cnn_dropout": 0.25,
            "arch_pool": 2,
            "arch_lstm_hidden": 128,
            "arch_lstm_layers": 1,
            "arch_fc_hidden": 128,
        })

        locations = db.run(_with_session(dataset_locations, platform, files))

        per_file: dict[str, tuple] = {}
        with tempfile.TemporaryDirectory() as tmp:
            for filename in files:
                bucket, key = locations[filename]
                local = os.path.join(tmp, filename)
                download_object(bucket, key, local)
                per_file[filename] = load_csv(local)

        def window_segments(segments: dict, offset=0):
            """구간 모음을 윈도우 배열로"""
            xs, ys = [], []
            for signals, labels in segments.values():
                w, yy = sliding_window(signals, labels, CLASSES, offset=offset)
                if len(w):
                    xs.append(w)
                    ys.append(yy)
            if not xs:
                return np.empty((0, 200, 6), np.float32), np.empty((0,), np.int64)
            return np.concatenate(xs), np.concatenate(ys)

        EVAL_FRAC = 0.1

        train_seg, val_seg, test_seg = {}, {}, {}
        for fn, (signals, labels) in per_file.items():
            n = len(signals)
            eval_len = max(int(n * EVAL_FRAC), WINDOW)
            if n - 2 * eval_len < WINDOW:
                train_seg[fn] = (signals, labels)
                continue
            a, b = n - 2 * eval_len, n - eval_len
            train_seg[fn] = (signals[:a], labels[:a])
            val_seg[fn] = (signals[a:b], labels[a:b])
            test_seg[fn] = (signals[b:], labels[b:])

        X_val, y_val = window_segments(val_seg)
        X_te, y_te = window_segments(test_seg)
        if not len(X_val) or not len(X_te):
            raise ValueError("val/test 윈도우가 없습니다 — 선택한 파일들이 전부 너무 짧습니다")
        mlflow.set_tag("split", "per_file_time_80_10_10")
        mlflow.log_param("num_files_eval", len(val_seg))

        X_train_base, _ = window_segments(train_seg)
        mean, std = compute_stats(X_train_base)

        def to_loader(X, y, shuffle):
            """텐서 → DataLoader"""
            ds = TensorDataset(torch.tensor(X), torch.tensor(y))
            return DataLoader(ds, batch_size=64, shuffle=shuffle)

        val_loader = to_loader(normalize(X_val, mean, std), y_val, False)
        test_loader = to_loader(normalize(X_te, mean, std), y_te, False)

        def epoch_train_loader():
            """매 에폭 랜덤 오프셋으로 train 구간을 재윈도잉(위상 증강)"""
            off = random.randrange(STRIDE)
            Xa, ya = window_segments(train_seg, offset=off)
            return to_loader(normalize(Xa, mean, std), ya, True)

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = FitSetModel(num_classes=len(CLASSES)).to(device)
        optimizer = torch.optim.Adam(model.parameters(), lr=lr)
        criterion = nn.CrossEntropyLoss()

        for epoch in range(1, epochs + 1):
            train_loader = epoch_train_loader()
            model.train()
            train_loss = 0.0
            for xb, yb in train_loader:
                xb, yb = xb.to(device), yb.to(device)
                optimizer.zero_grad()
                loss = criterion(model(xb), yb)
                loss.backward()
                optimizer.step()
                train_loss += loss.item() * len(xb)
            train_loss /= len(train_loader.dataset)

            model.eval()
            val_loss, val_correct = 0.0, 0
            with torch.no_grad():
                for xb, yb in val_loader:
                    xb, yb = xb.to(device), yb.to(device)
                    out = model(xb)
                    val_loss += criterion(out, yb).item() * len(xb)
                    val_correct += (out.argmax(1) == yb).sum().item()
            val_loss /= len(val_loader.dataset)
            val_acc = val_correct / len(val_loader.dataset)

            mlflow.log_metrics({
                "epoch": epoch,
                "train_loss": round(train_loss, 4),
                "val_loss": round(val_loss, 4),
                "val_accuracy": round(val_acc, 4),
            }, step=epoch)

        from sklearn.metrics import classification_report, confusion_matrix, f1_score

        model.eval()
        all_preds, all_true = [], []
        test_correct = 0
        with torch.no_grad():
            for xb, yb in test_loader:
                xb, yb = xb.to(device), yb.to(device)
                preds = model(xb).argmax(1)
                all_preds.extend(preds.cpu().numpy())
                all_true.extend(yb.cpu().numpy())
                test_correct += (preds == yb).sum().item()

        test_acc = test_correct / len(test_loader.dataset)
        f1 = f1_score(all_true, all_preds, average="macro")

        label_ids = list(range(len(CLASSES)))
        per_class_f1 = f1_score(all_true, all_preds, average=None, labels=label_ids, zero_division=0)

        mlflow.log_metrics({
            "test_accuracy": round(test_acc, 4),
            "f1_macro": round(f1, 4),
            **{f"f1_{CLASSES[i]}": round(float(v), 4) for i, v in enumerate(per_class_f1)},
        })

        mlflow.log_dict(
            classification_report(
                all_true, all_preds,
                labels=label_ids, target_names=CLASSES,
                output_dict=True, zero_division=0,
            ),
            "classification_report.json",
        )
        mlflow.log_dict(
            {
                "labels": CLASSES,
                "matrix": confusion_matrix(all_true, all_preds, labels=label_ids).tolist(),
            },
            "confusion_matrix.json",
        )

        model.cpu()
        mlflow.pytorch.log_model(
            pytorch_model=model,
            artifact_path="pytorch_model",
            serialization_format=mlflow.pytorch.SERIALIZATION_FORMAT_PICKLE,
        )

        with tempfile.TemporaryDirectory() as out:
            pt_path = os.path.join(out, "model.pt")
            torch.save(model.state_dict(), pt_path)
            upload_model_artifact(platform, version, pt_path, "model.pt")

            if platform == "ios":
                pkg_path = os.path.join(out, "FitSet.mlpackage")
                try:
                    from app.worker.convert import to_mlpackage
                    zip_path = to_mlpackage(model.cpu(), mean, std, pkg_path)
                    upload_model_artifact(platform, version, zip_path, "FitSet.mlpackage.zip")
                except ImportError:
                    mlflow.set_tag("convert_warning", "coremltools not installed")
            else:
                onnx_path = os.path.join(out, "FitSet.onnx")
                try:
                    from app.worker.convert import to_onnx
                    to_onnx(model.cpu(), mean, std, onnx_path)
                    upload_model_artifact(platform, version, onnx_path, "FitSet.onnx")
                except ImportError:
                    mlflow.set_tag("convert_warning", "onnx not installed")

            ext = "mlpackage.zip" if platform == "ios" else "onnx"
            model_url = f"s3://{settings.models_bucket}/{platform}/{version}/FitSet.{ext}"
            meta = {
                "platform": platform,
                "version": version,
                "classes": CLASSES,
                "input_shape": [1, 200, 6],
                "mean": mean,
                "std": std,
                "val_accuracy": round(val_acc, 4),
                "test_accuracy": round(test_acc, 4),
                "f1_macro": round(f1, 4),
                "trained_files": files,
                "model_url": model_url,
                "mlflow_run_id": run_id,
            }
            meta_path = os.path.join(out, "meta.json")
            Path(meta_path).write_text(json.dumps(meta, indent=2))
            upload_model_artifact(platform, version, meta_path, "meta.json")
            mlflow.log_artifact(meta_path)

        db.run(_with_session(mark_trained, platform, files, version))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", required=True)
    parser.add_argument("--files", required=True)
    parser.add_argument("--epochs", type=int, default=200)
    parser.add_argument("--lr", type=float, default=0.001)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()

    run(
        platform=args.platform,
        files=json.loads(args.files),
        epochs=args.epochs,
        lr=args.lr,
        run_id=args.run_id,
        version=args.version,
    )
