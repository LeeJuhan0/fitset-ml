# mlflow — 추적 서버 이미지. 빌드 시 EBS 백업 sqlite를 구워 기존 실험·모델 로그를 그대로 조회한다.
#   빌드 전 준비(git 미추적): aws s3 cp s3://fitset-models/backup/mlflow-20260824.db services/mlflow/mlflow.db
#   docker buildx build --platform linux/amd64 -f services/mlflow/Dockerfile .
# k8s(EKS)에서는 BACKEND_STORE_URI를 stage RDS MySQL로 주입해 무상태로 뜬다 — 굽은 sqlite는
# 로컬 조회·마이그레이션 원본용. (클러스터에 EBS CSI가 없어 PVC 불가 — infra README 결정)
FROM python:3.11-slim

RUN pip install --no-cache-dir mlflow boto3 pymysql   # pymysql: 백엔드 스토어 RDS MySQL(mysql+pymysql://) 접속용

# 굽는 스냅샷 — 마운트가 덮으면 볼륨이 우선한다
COPY services/mlflow/mlflow.db /mlflow/mlflow.db

# 전부 env로 재정의 가능 — 사이드카(localhost)든 별도 서비스(클러스터 DNS)든 배선만 바꾼다
ENV BACKEND_STORE_URI=sqlite:////mlflow/mlflow.db \
    ARTIFACT_ROOT=s3://fitset-models/mlflow \
    ALLOWED_HOSTS=localhost:5001,127.0.0.1:5001,mlflow:5001 \
    CORS_ORIGINS=http://localhost:5001

EXPOSE 5001

# shell form — env 확장 필요
CMD mlflow server \
    --backend-store-uri "$BACKEND_STORE_URI" \
    --default-artifact-root "$ARTIFACT_ROOT" \
    --host 0.0.0.0 --port 5001 \
    --static-prefix /mlflow \
    --allowed-hosts "$ALLOWED_HOSTS" \
    --cors-allowed-origins "$CORS_ORIGINS"
