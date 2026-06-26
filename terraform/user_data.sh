#!/bin/bash
set -e

# ── 패키지 설치 ────────────────────────────────────────────────────────────────
dnf update -y
dnf install -y git python3.11 python3.11-pip rsync

# ── EBS 마운트 (/mlflow) ────────────────────────────────────────────────────────
if ! blkid /dev/xvdf; then
  mkfs.ext4 /dev/xvdf
fi
mkdir -p /mlflow
mount /dev/xvdf /mlflow
echo "/dev/xvdf /mlflow ext4 defaults,nofail 0 2" >> /etc/fstab

# ── 앱 디렉터리 준비 (코드는 GitHub Actions가 rsync로 밀어줌) ──────────────────────
mkdir -p /app
chown ec2-user:ec2-user /app

# ── systemd: MLflow ─────────────────────────────────────────────────────────────
cat > /etc/systemd/system/mlflow.service << 'EOF'
[Unit]
Description=MLflow Tracking Server
After=network.target

[Service]
User=ec2-user
WorkingDirectory=/app
ExecStart=/home/ec2-user/.local/bin/mlflow server \
  --backend-store-uri sqlite:////mlflow/mlflow.db \
  --default-artifact-root s3://fitset-models/mlflow \
  --host 0.0.0.0 \
  --port 5001
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# ── systemd: FastAPI ─────────────────────────────────────────────────────────────
cat > /etc/systemd/system/fitset-api.service << 'EOF'
[Unit]
Description=FitSet ML API Server
After=network.target mlflow.service

[Service]
User=ec2-user
WorkingDirectory=/app
Environment="MLFLOW_TRACKING_URI=http://localhost:5001"
Environment="RAW_DATA_BUCKET=fitset-dataset"
Environment="MODELS_BUCKET=fitset-models"
Environment="AWS_REGION=ap-northeast-2"
ExecStart=/home/ec2-user/.local/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable mlflow fitset-api
