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

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
