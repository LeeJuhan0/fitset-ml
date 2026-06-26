#!/bin/bash
set -e

# ── 패키지 설치 ────────────────────────────────────────────────────────────────
dnf update -y
dnf install -y rsync docker

# ── Docker 활성화 ──────────────────────────────────────────────────────────────
systemctl enable --now docker
usermod -aG docker ec2-user

# ── Docker Compose v2 플러그인 ─────────────────────────────────────────────────
ARCH=$(uname -m)
mkdir -p /usr/local/lib/docker/cli-plugins
curl -fsSL "https://github.com/docker/compose/releases/download/v2.27.0/docker-compose-linux-${ARCH}" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

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
