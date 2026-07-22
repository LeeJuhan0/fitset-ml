FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# base + 변환(iOS/CoreML) 의존성 — 워커가 컨테이너 안에서 .mlpackage 변환을 수행.
# Android(ai-edge-torch=TF/JAX)는 requirements-convert.txt에서 보류 상태라 이미지가 가볍게 유지됨.
COPY requirements/requirements.txt requirements/requirements-convert.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-convert.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
