# user_api — 유저 트래픽 전용 슬림 이미지. 빌드 컨텍스트는 레포 루트:
#   docker buildx build --platform linux/amd64 -f services/user_api/Dockerfile .
FROM python:3.11-slim

WORKDIR /srv

COPY requirements/requirements-user.txt ./
RUN pip install --no-cache-dir -r requirements-user.txt

COPY libs/common /srv/libs/common
COPY services/user_api /srv/services/user_api

ENV PYTHONPATH=/srv/libs/common:/srv/services/user_api

EXPOSE 8000

CMD ["uvicorn", "user_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
