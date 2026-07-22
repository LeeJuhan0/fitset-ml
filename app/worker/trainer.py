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
from sklearn.model_selection import GroupShuffleSplit, train_test_split
from torch.utils.data import DataLoader, TensorDataset

from app.core.config import CLASSES, settings
from app.core.s3 import download_csv, get_index, mark_trained, upload_model_artifact
from app.worker.model_def import FitSetModel
from app.worker.preprocess import STRIDE, compute_stats, load_csv, normalize, sliding_window

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
#   GroupShuffleSplit  : (sklearn 클래스) "그룹(=파일) 단위"로 데이터를 나눠 누수를 막는 분할기
#   train_test_split   : (sklearn 함수) 단순 무작위 분할(파일 수가 적을 때 폴백용)
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

        def window_files(file_list, offset=0):
            """주어진 파일들을 윈도우로 잘라 (X[M,200,6], y[M], groups[M]) 반환.
            groups = 각 윈도우의 출신 filename — 파일 단위 분할·누수 차단용."""
            xs, ys, gs = [], [], []
            for fn in file_list:
                signals, labels = per_file[fn]
                w, yy = sliding_window(signals, labels, CLASSES, offset=offset)
                if len(w):
                    xs.append(w)
                    ys.append(yy)
                    gs.append(np.array([fn] * len(w)))
            if not xs:
                return (np.empty((0, 200, 6), np.float32),
                        np.empty((0,), np.int64),
                        np.empty((0,), object))
            return np.concatenate(xs), np.concatenate(ys), np.concatenate(gs)

        # 기준 윈도우(offset=0) — 분할·통계·평가셋의 기준
        X0, y0, groups = window_files(files, offset=0)

        # ── 2. 분할 — 파일(recording) 단위 GroupShuffleSplit ───────────
        # 같은 파일의 겹치는 윈도우가 train/test에 흩어지면 누수 → 정확도 과대평가.
        # 파일이 적으면(MVP) 윈도우 단위 무작위 분할로 폴백한다.
        #
        # [GroupShuffleSplit 클래스(sklearn)란]
        #   train_test_split과 달리 "그룹 id"를 받아, 같은 그룹은 통째로 한쪽(train 또는 test)에만
        #   가도록 보장하는 분할기. 여기선 groups=윈도우의 출신 파일명 → "한 파일의 윈도우들은
        #   절대 train과 test로 쪼개지지 않는다". 그래서 옆 윈도우끼리 겹쳐 생기는 정보 누수를 차단.
        #   .split(X, y, groups) 가 (train_idx, test_idx) 인덱스 쌍을 yield → next()로 1개만 꺼냄.
        #   여기선 두 번 적용: 먼저 70/30(train / tmp), 다시 tmp를 50/50(val / test)로.
        train_files = None  # None이면 폴백(오프셋 증강 없음)
        try:
            if len(set(groups)) < 4:
                raise ValueError("그룹(파일) 수 부족 → 폴백")
            g1 = GroupShuffleSplit(n_splits=1, test_size=0.3, random_state=42)
            tr_idx, tmp_idx = next(g1.split(X0, y0, groups))
            g2 = GroupShuffleSplit(n_splits=1, test_size=0.5, random_state=42)
            v_rel, te_rel = next(g2.split(X0[tmp_idx], y0[tmp_idx], groups[tmp_idx]))
            val_idx, test_idx = tmp_idx[v_rel], tmp_idx[te_rel]
            if not (len(tr_idx) and len(val_idx) and len(test_idx)):
                raise ValueError("분할 결과 빈 셋 → 폴백")
            train_files = sorted(set(groups[tr_idx]))
            X_val, y_val = X0[val_idx], y0[val_idx]
            X_te, y_te = X0[test_idx], y0[test_idx]
            mlflow.set_tag("split", "group_by_file")
        except ValueError:
            # 윈도우 단위 무작위 분할 (구버전 동작, 오프셋 증강 없음)
            try:
                X_tr0, X_tmp, y_tr0, y_tmp = train_test_split(X0, y0, test_size=0.3, stratify=y0, random_state=42)
                X_val, X_te, y_val, y_te = train_test_split(X_tmp, y_tmp, test_size=0.5, stratify=y_tmp, random_state=42)
            except ValueError:
                X_tr0, X_tmp, y_tr0, y_tmp = train_test_split(X0, y0, test_size=0.3, random_state=42)
                X_val, X_te, y_val, y_te = train_test_split(X_tmp, y_tmp, test_size=0.5, random_state=42)
            mlflow.set_tag("split", "window_fallback")

        # ── 3. 정규화 통계 — train에서만 산출 (통계 누수 차단) ──────────
        X_train_base = window_files(train_files, offset=0)[0] if train_files is not None else X_tr0
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

        # 폴백(윈도우 분할)이면 train 고정 — 오프셋 증강은 파일 분할일 때만
        fixed_train_loader = to_loader(normalize(X_tr0, mean, std), y_tr0, True) if train_files is None else None

        def epoch_train_loader():
            """파일 분할이면 매 에폭 랜덤 오프셋으로 재윈도잉(위상 증강),
            폴백이면 고정 로더 반환."""
            if fixed_train_loader is not None:
                return fixed_train_loader
            off = random.randrange(STRIDE)            # [0, 100) — 위상 무작위
            Xa, ya, _ = window_files(train_files, offset=off)
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

        # 에폭 반복: 매 에폭마다 train 1회 + val 1회. 파일 분할이면 train 로더를 매번 새로(랜덤 오프셋) 만든다.
        for epoch in range(1, epochs + 1):
            train_loader = epoch_train_loader()   # 파일 분할이면 매 에폭 랜덤 오프셋 재윈도잉
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
        from sklearn.metrics import f1_score

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

        mlflow.log_metrics({
            "test_accuracy": round(test_acc, 4),
            "f1_macro": round(f1, 4),
        })

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
                tflite_path = os.path.join(out, "FitSet.tflite")
                try:
                    from app.worker.convert import to_tflite
                    to_tflite(model.cpu(), mean, std, tflite_path)
                    upload_model_artifact(platform, version, tflite_path, "FitSet.tflite")
                except ImportError:
                    mlflow.set_tag("convert_warning", "ai.edge.torch not installed")

            ext = "mlpackage.zip" if platform == "ios" else "tflite"
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
