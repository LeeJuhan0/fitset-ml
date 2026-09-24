# 관리자 웹서버 이미지. 정적 대시보드, API, 파일 목록(sqlite), 학습·라벨링 worker(subprocess) 포함.
#   docker buildx build --platform linux/amd64 -t fitset-ml-admin-api .
FROM python:3.11-slim

WORKDIR /srv

# libgl1·libglib2.0-0 은 opencv 가 import 때, libgles2·libegl1 은 mediapipe tasks C 바인딩(libmediapipe.so) 로드 때 요구한다
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libgl1 libglib2.0-0 libgles2 libegl1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/requirements.txt requirements/requirements-convert.txt requirements/requirements-vision.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-convert.txt -r requirements-vision.txt

ADD https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task /srv/models/pose_landmarker_full.task

COPY app /srv/app
COPY scripts /srv/scripts
COPY db /srv/db
COPY alembic /srv/alembic
COPY alembic.ini /srv/alembic.ini
COPY docker/entrypoint.sh /srv/docker/entrypoint.sh

ENV PYTHONPATH=/srv
ENV POSE_MODEL_PATH=/srv/models/pose_landmarker_full.task

EXPOSE 8000

ENTRYPOINT ["/srv/docker/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
