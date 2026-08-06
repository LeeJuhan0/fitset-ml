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
import random
import tempfile
from pathlib import Path

import mlflow
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from app.core.config import CLASSES, settings
from app.core.s3 import download_csv, get_index, mark_trained, upload_model_artifact
from app.worker.model_def import FitSetModel
from app.worker.preprocess import STRIDE, WINDOW, compute_stats, load_csv, normalize, sliding_window

# ─────────────────────────────────────────────────────────────────────────────
# [이 파일이 하는 일 — 학습 워커]
#   웹(FastAPI) 핸들러가 미리 만들어 RUNNING 상태로 열어둔 MLflow run_id를 인자로
#   넘겨받아, 별도 프로세스에서 학습 파이프라인 전체를 끝까지 수행한다:
#     1) S3에서 CSV 다운로드        2) 슬라이딩 윈도우로 학습 데이터 구성
#     3) train/val/test 분할        4) CNN-LSTM 학습 + 에폭마다 메트릭 기록
#     5) test 평가                  6) 모델 저장·플랫폼별 변환·S3 업로드
#     7) index.json에 학습 사용 표시
#
# [import한 심볼·클래스의 역할]
#   FitSetModel        : 우리가 정의한 CNN-LSTM 분류 모델 클래스 (model_def.py). 학습 루프 위 설명 참고.
#   load_csv           : CSV → (signals[N,6], labels[N])
#   sliding_window     : 신호를 200샘플(=2초) 윈도우로 잘라 (X[M,200,6], y[M]) 생성
#   compute_stats      : 채널별 mean·std 산출(정규화 기준값)   normalize: 그 값으로 정규화
#   TensorDataset      : (torch 클래스) (X, y) 텐서를 한 묶음(샘플=윈도우)으로 감싸는 데이터셋
#   DataLoader         : (torch 클래스) 데이터셋을 배치 단위로 꺼내주고 셔플하는 반복자
#   mlflow             : 학습 추적 라이브러리 (run/params/metrics/artifact 기록)
# ─────────────────────────────────────────────────────────────────────────────


def run(platform: str, files: list[str], epochs: int, lr: float, run_id: str, version: str):
    # run_id: 웹 핸들러가 만든 기존 run에 "이어 붙는다". version: 모델 버전(예: v1.0)
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)

    # start_run(run_id=...) : 새 run을 만드는 게 아니라 그 run_id의 run에 재접속(reattach).
    #   web의 create_run()은 RUNNING으로 열기만 했고, 여기 with 블록이 끝날 때 비로소
    #   FINISHED로 마감된다 → run의 "끝"은 학습을 실제로 하는 이 워커가 책임진다.
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

        # ── 1. CSV 다운로드 (파일별 원신호 보관) ───────────────────────
        # 인덱스(S3의 파일 목록 메타)에서 "파일명 → 종목(class)" 매핑을 만든다.
        # 종목을 알아야 S3 키 {platform}/raw/{CLASS}/{filename} 를 조립해 내려받을 수 있다.
        index = get_index(platform)
        file_map = {f["filename"]: f["class"] for f in index["files"]}

        # 파일별 원신호를 메모리에 보관 → 뒤에서 오프셋만 바꿔 여러 번 다시 윈도잉하기 위함.
        # 임시 디렉토리는 with 블록을 나가면 자동 삭제(CSV 원본은 메모리에 이미 올렸으니 OK).
        per_file: dict[str, tuple] = {}   # filename -> (signals[N,6], labels[N])
        with tempfile.TemporaryDirectory() as tmp:
            for filename in files:
                class_name = file_map[filename]
                local = os.path.join(tmp, filename)
                download_csv(platform, class_name, filename, local)   # S3 → 임시파일
                per_file[filename] = load_csv(local)                  # CSV → (signals, labels)

        def window_segments(segments: dict, offset=0):
            """구간 모음 {filename: (signals, labels)} 을 윈도우로 잘라 (X[M,200,6], y[M]) 반환."""
            xs, ys = [], []
            for signals, labels in segments.values():
                w, yy = sliding_window(signals, labels, CLASSES, offset=offset)
                if len(w):
                    xs.append(w)
                    ys.append(yy)
            if not xs:
                return np.empty((0, 200, 6), np.float32), np.empty((0,), np.int64)
            return np.concatenate(xs), np.concatenate(ys)

        # ── 2. 분할 — 각 파일을 시간순으로 잘라 train / val 10% / test 10% ──
        # 이전의 파일 단위 무작위 분할(GroupShuffleSplit)은 종목당 파일이 적으면 특정
        # 종목이 val/test에서 통째로 빠질 수 있었다 → 모든 파일이 뒤쪽 10%+10%를
        # val/test에 내놓도록 파일 "안에서" 시간순으로 자른다. 모든 종목이 평가셋에
        # 포함되고, 학습을 안 한 종목을 평가하는 일도 없다.
        #   · 구간별로 따로 윈도잉하므로 경계를 걸치는 윈도우가 없고, 겹치는 이웃
        #     윈도우가 train/평가셋에 흩어지는 누수도 그대로 차단된다.
        #   · 10%가 윈도우 1개(2초)보다 짧은 파일은 val·test에 최소 2초씩 확보하고,
        #     그마저 안 나오는 초단편 파일은 train 전용으로 돌린다.
        #   · val/test가 각 파일의 마지막 구간이므로 "세트 후반(지친 상태) 동작"을
        #     평가하는 셈 — 시계열에서 미래 구간 평가는 표준적인 관행이다.
        EVAL_FRAC = 0.1   # val·test 각각의 비율(나머지 ≈80%가 train)

        train_seg, val_seg, test_seg = {}, {}, {}
        for fn, (signals, labels) in per_file.items():
            n = len(signals)
            eval_len = max(int(n * EVAL_FRAC), WINDOW)   # val·test 각각의 샘플 수
            if n - 2 * eval_len < WINDOW:                # train 윈도우가 1개도 안 남으면
                train_seg[fn] = (signals, labels)        # train 전용(평가 기여 없음)
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
        mlflow.log_param("num_files_eval", len(val_seg))   # 평가에 실제 기여한 파일 수

        # ── 3. 정규화 통계 — train 구간에서만 산출 (통계 누수 차단) ──────
        X_train_base, _ = window_segments(train_seg)
        mean, std = compute_stats(X_train_base)

        def to_loader(X, y, shuffle):
            # TensorDataset : (X, y) 두 텐서를 인덱스로 짝지어 ds[i] = (X[i], y[i]) 로 꺼내는 컨테이너.
            # DataLoader    : 그 데이터셋을 batch_size(64)씩 묶고, shuffle=True면 매 에폭 순서를 섞어
            #                 (xb, yb) 미니배치를 반복(iterate)하게 해주는 클래스. 학습 루프가 이걸 돈다.
            ds = TensorDataset(torch.tensor(X), torch.tensor(y))
            return DataLoader(ds, batch_size=64, shuffle=shuffle)

        # 평가셋: train 통계로 정규화, offset=0 고정
        val_loader = to_loader(normalize(X_val, mean, std), y_val, False)
        test_loader = to_loader(normalize(X_te, mean, std), y_te, False)

        def epoch_train_loader():
            """매 에폭 랜덤 오프셋으로 train 구간을 재윈도잉(위상 증강)."""
            off = random.randrange(STRIDE)            # [0, 100) — 위상 무작위
            Xa, ya = window_segments(train_seg, offset=off)
            return to_loader(normalize(Xa, mean, std), ya, True)

        # ── 2. 학습 ─────────────────────────────────────────────────────
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")  # GPU 있으면 GPU
        model = FitSetModel(num_classes=len(CLASSES)).to(device)
        optimizer = torch.optim.Adam(model.parameters(), lr=lr)   # 가중치 갱신 규칙(Adam)
        criterion = nn.CrossEntropyLoss()                          # 분류 손실(정답 vs 예측 logits)
        # [FitSetModel 클래스(model_def.py)의 구성 — 입력 [B,200,6], 출력 [B,5] logits]
        #   conv : Conv1d(6→256, k=5) → BatchNorm → ReLU → MaxPool(2) → Dropout(0.25)
        #          └ 6채널 IMU 시계열에서 지역적 패턴 추출, 길이 200→100으로 절반 다운샘플
        #   lstm : LSTM(256→128). 시간축(100스텝)의 흐름을 요약 → 마지막 hidden state[ B,128 ] 사용
        #   fc   : Linear(128→128) → ReLU → Linear(128→num_classes). 최종 종목별 점수(logits)
        #   forward에서 permute로 [B,200,6]↔[B,6,200] 축을 Conv1d/LSTM 입력 규격에 맞춰 바꿈.
        #   (별도 WrappedModel은 여기서 안 씀 — 변환 단계 convert.py에서 정규화+softmax 입혀 export)

        # 에폭 반복: 매 에폭마다 train 1회 + val 1회. train 로더는 매번 새로(랜덤 오프셋) 만든다.
        for epoch in range(1, epochs + 1):
            train_loader = epoch_train_loader()   # 매 에폭 랜덤 오프셋 재윈도잉
            model.train()                          # 학습 모드(Dropout·BatchNorm 활성)
            train_loss = 0.0
            for xb, yb in train_loader:            # 미니배치 반복
                xb, yb = xb.to(device), yb.to(device)
                optimizer.zero_grad()              # 이전 배치의 기울기 초기화
                loss = criterion(model(xb), yb)    # 순전파 + 손실 계산
                loss.backward()                    # 역전파(기울기 계산)
                optimizer.step()                   # 가중치 갱신
                train_loss += loss.item() * len(xb)   # 배치 손실 합(샘플 수로 가중)
            train_loss /= len(train_loader.dataset)   # 에폭 평균 손실

            model.eval()                           # 평가 모드(Dropout off, BatchNorm 고정)
            val_loss, val_correct = 0.0, 0
            with torch.no_grad():                  # 기울기 계산 끔(메모리·속도)
                for xb, yb in val_loader:
                    xb, yb = xb.to(device), yb.to(device)
                    out = model(xb)                          # logits [B,5]
                    val_loss += criterion(out, yb).item() * len(xb)
                    val_correct += (out.argmax(1) == yb).sum().item()  # argmax=예측 종목, 정답과 일치 수
            val_loss /= len(val_loader.dataset)
            val_acc = val_correct / len(val_loader.dataset)   # 검증 정확도

            mlflow.log_metrics({
                "epoch": epoch,
                "train_loss": round(train_loss, 4),
                "val_loss": round(val_loss, 4),
                "val_accuracy": round(val_acc, 4),
            }, step=epoch)

        # ── 3. 평가 ─────────────────────────────────────────────────────
        # 학습에 한 번도 안 쓴 test 셋으로 최종 성능 측정. f1_score(average="macro")는
        # 종목별 F1을 평균 → 클래스 불균형에서도 소수 종목 성능을 공정히 반영한다.
        from sklearn.metrics import classification_report, confusion_matrix, f1_score

        model.eval()
        all_preds, all_true = [], []   # 전체 예측/정답을 모아 f1 계산
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

        # 클래스별 F1 — average=None이면 클래스마다 F1 배열이 나온다.
        # labels를 명시해 test 셋에 없는 종목도 CLASSES 인덱스와 어긋나지 않게 정렬(없는 종목은 0).
        label_ids = list(range(len(CLASSES)))
        per_class_f1 = f1_score(all_true, all_preds, average=None, labels=label_ids, zero_division=0)

        mlflow.log_metrics({
            "test_accuracy": round(test_acc, 4),
            "f1_macro": round(f1, 4),
            **{f"f1_{CLASSES[i]}": round(float(v), 4) for i, v in enumerate(per_class_f1)},
        })

        # 클래스별 precision/recall까지 포함한 상세 리포트와 혼동 행렬은 run 아티팩트로 남긴다
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
                "labels": CLASSES,   # matrix[i][j] = 실제 labels[i]를 labels[j]로 예측한 윈도우 수
                "matrix": confusion_matrix(all_true, all_preds, labels=label_ids).tolist(),
            },
            "confusion_matrix.json",
        )

        # ── 4. 모델 저장 & 변환 & S3 업로드 ─────────────────────────────
        model.cpu()   # 변환·저장은 CPU 텐서 기준
        # mlflow.pytorch.log_model : 학습된 PyTorch 모델을 이 run의 아티팩트로 기록
        #   → artifact_root(이 프로젝트선 S3)에 'pytorch_model/'로 업로드. MLflow가 관리하는 사본.
        mlflow.pytorch.log_model(
            pytorch_model=model,
            artifact_path="pytorch_model",
            serialization_format=mlflow.pytorch.SERIALIZATION_FORMAT_PICKLE,
        )

        with tempfile.TemporaryDirectory() as out:
            pt_path = os.path.join(out, "model.pt")
            torch.save(model.state_dict(), pt_path)
            upload_model_artifact(platform, version, pt_path, "model.pt")

            # 플랫폼별 온디바이스 포맷으로 변환해 별도 경로로도 업로드(앱이 직접 받는 배포용).
            # 변환 함수 내부에서 학습 모델을 WrappedModel로 감싼다:
            #   WrappedModel = 입력 정규화((x-mean)/std) + FitSetModel + softmax 를 한 그래프에 내장한 클래스.
            #   → 앱은 raw IMU 값을 그대로 넣으면 확률이 나온다(전처리/후처리를 모델에 포함시켜 단순화).
            # coremltools / ai.edge.torch 가 안 깔린 환경이면 변환만 건너뛰고 태그로 표시(학습은 성공 처리).
            if platform == "ios":
                pkg_path = os.path.join(out, "FitSet.mlpackage")
                try:
                    from app.worker.convert import to_mlpackage
                    zip_path = to_mlpackage(model.cpu(), mean, std, pkg_path)   # → CoreML .mlpackage(zip)
                    upload_model_artifact(platform, version, zip_path, "FitSet.mlpackage.zip")
                except ImportError:
                    mlflow.set_tag("convert_warning", "coremltools not installed")
            else:
                onnx_path = os.path.join(out, "FitSet.onnx")
                try:
                    from app.worker.convert import to_onnx
                    to_onnx(model.cpu(), mean, std, onnx_path)     # → ONNX(앱은 ONNX Runtime 로드)
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

        # ── 5. index.json 업데이트 ───────────────────────────────────────
        # 이번에 학습에 쓴 파일들의 trainedInVersion 을 현재 version 으로 표시 →
        # 대시보드가 "어떤 파일이 어느 버전 학습에 쓰였는지" 추적. (with 블록 종료 시 run이 FINISHED 됨)
        mark_trained(platform, files, version)


# [엔트리포인트] 웹이 subprocess로 `python -m app.worker.trainer --platform ... --run-id ...` 처럼
# 실행하면 이 블록이 돈다. CLI 인자를 파싱해 run(...)을 호출하는 게 전부.
# --files 는 JSON 문자열로 받으므로 json.loads 로 리스트 복원.
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
