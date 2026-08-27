# admin_api — 대시보드·학습·배포·승격 + 학습 worker(subprocess) 포함 이미지.
# 변환 의존성(coremltools·onnx)까지 실어 워커가 컨테이너 안에서 모델 변환을 수행한다.
# 빌드 컨텍스트는 레포 루트:
#   docker buildx build --platform linux/amd64 -f services/admin_api/Dockerfile .
FROM python:3.11-slim

WORKDIR /srv

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/requirements.txt requirements/requirements-convert.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-convert.txt

COPY libs/common /srv/libs/common
COPY services/admin_api /srv/services/admin_api

ENV PYTHONPATH=/srv/libs/common:/srv/services/admin_api

EXPOSE 8000

CMD ["uvicorn", "admin_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
