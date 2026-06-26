"""학습 워커 — FastAPI 서버가 subprocess로 spawn함

실행:
    python -m app.worker.trainer \
        --platform ios \
        --files '["SQUAT_001.csv","PUSHUP_001.csv"]' \
        --epochs 200 --lr 0.001 \
        --run-id <mlflow_run_id> \
        --version v1.0
"""

import argparse
import json
import os
import tempfile
from pathlib import Path

import mlflow
import numpy as np
import torch
import torch.nn as nn
from sklearn.model_selection import train_test_split
from torch.utils.data import DataLoader, TensorDataset

from app.core.config import CLASSES, settings
from app.core.s3 import download_csv, get_index, mark_trained, upload_model_artifact
from app.worker.model_def import FitSetModel
from app.worker.preprocess import compute_stats, load_csv, normalize, sliding_window


def run(platform: str, files: list[str], epochs: int, lr: float, run_id: str, version: str):
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)

    with mlflow.start_run(run_id=run_id):
        mlflow.log_params({
            # 학습 설정
            "platform": platform,
            "epochs": epochs,
            "lr": lr,
            "batch_size": 64,
            "optimizer": "Adam",
            "num_files": len(files),
            "files": json.dumps(files),
            "num_classes": len(CLASSES),
            # 모델 아키텍처
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

        # ── 1. CSV 다운로드 & 전처리 ────────────────────────────────────
        index = get_index(platform)
        file_map = {f["filename"]: f["class"] for f in index["files"]}

        all_windows, all_labels = [], []
        with tempfile.TemporaryDirectory() as tmp:
            for filename in files:
                class_name = file_map[filename]
                local = os.path.join(tmp, filename)
                download_csv(platform, class_name, filename, local)
                signals, labels = load_csv(local)
                w, y = sliding_window(signals, labels, CLASSES)
                all_windows.append(w)
                all_labels.append(y)

        X = np.concatenate(all_windows)
        y = np.concatenate(all_labels)

        mean, std = compute_stats(X)
        X_norm = normalize(X, mean, std)

        # train 70 / val 15 / test 15
        try:
            X_tr, X_tmp, y_tr, y_tmp = train_test_split(X_norm, y, test_size=0.3, stratify=y, random_state=42)
            X_val, X_te, y_val, y_te = train_test_split(X_tmp, y_tmp, test_size=0.5, stratify=y_tmp, random_state=42)
        except ValueError:
            # 데이터가 너무 적을 때 stratify 없이 분할
            X_tr, X_tmp, y_tr, y_tmp = train_test_split(X_norm, y, test_size=0.3, random_state=42)
            X_val, X_te, y_val, y_te = train_test_split(X_tmp, y_tmp, test_size=0.5, random_state=42)

        def to_loader(X, y, shuffle):
            ds = TensorDataset(torch.tensor(X), torch.tensor(y))
            return DataLoader(ds, batch_size=64, shuffle=shuffle)

        train_loader = to_loader(X_tr, y_tr, True)
        val_loader   = to_loader(X_val, y_val, False)
        test_loader  = to_loader(X_te, y_te, False)

        # ── 2. 학습 ─────────────────────────────────────────────────────
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = FitSetModel(num_classes=len(CLASSES)).to(device)
        optimizer = torch.optim.Adam(model.parameters(), lr=lr)
        criterion = nn.CrossEntropyLoss()

        for epoch in range(1, epochs + 1):
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

        # ── 3. 평가 ─────────────────────────────────────────────────────
        from sklearn.metrics import f1_score

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

        mlflow.log_metrics({
            "test_accuracy": round(test_acc, 4),
            "f1_macro": round(f1, 4),
        })

        # ── 4. 모델 저장 & 변환 & S3 업로드 ─────────────────────────────
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
                    to_mlpackage(model.cpu(), mean, std, pkg_path)
                    upload_model_artifact(platform, version, pkg_path, "FitSet.mlpackage")
                except ImportError:
                    mlflow.set_tag("convert_warning", "coremltools not installed")
            else:
                tflite_path = os.path.join(out, "FitSet.tflite")
                try:
                    from app.worker.convert import to_tflite
                    to_tflite(model.cpu(), mean, std, tflite_path)
                    upload_model_artifact(platform, version, tflite_path, "FitSet.tflite")
                except ImportError:
                    mlflow.set_tag("convert_warning", "ai.edge.torch not installed")

            ext = "mlpackage" if platform == "ios" else "tflite"
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
            import json as _json
            meta_path = os.path.join(out, "meta.json")
            Path(meta_path).write_text(_json.dumps(meta, indent=2))
            upload_model_artifact(platform, version, meta_path, "meta.json")
            mlflow.log_artifact(meta_path)

        # ── 5. index.json 업데이트 ───────────────────────────────────────
        mark_trained(platform, files, version)


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
