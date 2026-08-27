FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# base + 변환 의존성 — 워커가 컨테이너 안에서 iOS .mlpackage(coremltools)와
# Android .onnx(torch.onnx.export + onnx) 변환을 수행. 둘 다 t3.small에서 동작하는 무게.
COPY requirements/requirements.txt requirements/requirements-convert.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-convert.txt

COPY . .

# 멀티모듈 레이아웃 — 공통 코드는 libs/common, 엔트리포인트는 services/* (import 경로는 app.* 유지)
# 이 루트 Dockerfile은 과도기 통합 이미지(compose 로컬용) — 서비스별 이미지는 services/*/Dockerfile이 정본
ENV PYTHONPATH=/app/libs/common:/app/services/user_api:/app/services/admin_api

EXPOSE 8000

CMD ["uvicorn", "admin_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
