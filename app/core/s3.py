"""S3 스토리지 — fitset-raw-data(학습 데이터) / fitset-models(모델 아티팩트)"""

import json
import re
import threading
import time
from datetime import datetime, timezone
from typing import Callable

import boto3
from botocore.exceptions import ClientError

from .config import settings

# index.json 조건부 쓰기(낙관적 락) 충돌 시 재시도 횟수
_INDEX_MAX_RETRIES = 5

_s3 = None

def _client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3", region_name=settings.aws_region)
    return _s3


# ── 내부 경로 헬퍼 ──────────────────────────────────────────────────────────

def _index_key(platform: str) -> str:
    return f"{platform}/index.json"

def _csv_key(platform: str, class_name: str, filename: str) -> str:
    return f"{platform}/raw/{class_name}/{filename}"

def _model_key(platform: str, version: str, filename: str) -> str:
    return f"{platform}/{version}/{filename}"

def _latest_key(platform: str) -> str:
    return f"{platform}/latest.json"


# ── index.json ──────────────────────────────────────────────────────────────

def _get_index_with_etag(platform: str) -> tuple[dict, str | None]:
    """index.json 본문과 ETag를 함께 읽는다. 없으면 (빈 인덱스, None)."""
    try:
        obj = _client().get_object(
            Bucket=settings.raw_data_bucket,
            Key=_index_key(platform),
        )
        return json.loads(obj["Body"].read()), obj["ETag"]
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            return {"platform": platform, "files": []}, None
        raise


def get_index(platform: str) -> dict:
    data, _ = _get_index_with_etag(platform)
    return data


def put_index(platform: str, data: dict, *, etag: str):
    """index.json을 조건부 저장한다 (update_index 전용 내부 헬퍼).

    etag 있음  → IfMatch:    읽은 이후 다른 요청이 바꿨으면 412로 실패
    etag None  → IfNoneMatch: 그사이 다른 요청이 새로 만들었으면 412로 실패
    """
    extra = {"IfMatch": etag} if etag is not None else {"IfNoneMatch": "*"}

    _client().put_object(
        Bucket=settings.raw_data_bucket,
        Key=_index_key(platform),
        Body=json.dumps(data, ensure_ascii=False, indent=2),
        ContentType="application/json",
        **extra,
    )


def update_index(platform: str, mutate: Callable[[dict], None]) -> dict:
    """index.json을 원자적으로 read-modify-write 한다.

    여러 요청이 동시에 같은 플랫폼 인덱스를 갱신해도 lost update가 나지 않도록,
    ETag 기반 조건부 쓰기로 보호한다. 그사이 다른 요청이 인덱스를 바꿔 쓰기가
    거부되면(412/409), 최신본을 다시 읽어 mutate를 재적용하고 재시도한다.

    mutate(index)는 index dict를 제자리(in-place)에서 변경하는 콜백.
    """
    for attempt in range(_INDEX_MAX_RETRIES):
        data, etag = _get_index_with_etag(platform)
        mutate(data)
        try:
            put_index(platform, data, etag=etag)
            return data
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("PreconditionFailed", "ConditionalRequestConflict"):
                # 동시 쓰기 충돌 → 살짝 백오프 후 최신본으로 재시도
                time.sleep(0.05 * (attempt + 1))
                continue
            raise

    raise RuntimeError(f"index.json 동시 갱신 재시도 초과: {platform}")


def mark_trained(platform: str, filenames: list[str], version: str):
    name_set = set(filenames)

    def _mark(index: dict):
        for f in index["files"]:
            if f["filename"] in name_set:
                f["trainedInVersion"] = version

    update_index(platform, _mark)


# ── 파일명 예약(서버가 인덱스 보고 이름 부여) ────────────────────────────────

# 예약을 직렬화하는 인프로세스 락 — "동기 처리"로 동시 요청에 같은 번호가 안 나가게.
# (update_index의 ETag 조건부 쓰기가 교차 프로세스까지 보장하고, 이 락은 인프로세스 직렬화)
_reserve_lock = threading.Lock()


def reserve_upload(platform: str, class_name: str, device_id: str) -> str:
    """인덱스를 보고 다음 파일명을 정해 예약(uploaded=False)하고 그 파일명을 반환한다.

    파일명: ``{CLASS}_{deviceId}_{NNNN}.csv`` — 해당 class+deviceId의 다음 순번.
    동기 처리: 인프로세스 락 + update_index(낙관적 락)로 동시 요청에도 번호가
    중복되지 않게 직렬화한다.
    """
    assigned: dict = {}

    def _reserve(index: dict):
        files = index["files"]
        existing = {f["filename"] for f in files}
        seq = sum(
            1 for f in files
            if f.get("class") == class_name and f.get("deviceId") == device_id
        ) + 1
        filename = f"{class_name}_{device_id}_{seq:04d}.csv"
        while filename in existing:  # 구멍/중복 방지
            seq += 1
            filename = f"{class_name}_{device_id}_{seq:04d}.csv"
        files.append({
            "filename": filename,
            "class": class_name,
            "deviceId": device_id,
            "collectedAt": datetime.now(timezone.utc).isoformat(),
            "uploaded": False,
            "trainedInVersion": None,
        })
        assigned["filename"] = filename

    with _reserve_lock:
        update_index(platform, _reserve)
    return assigned["filename"]


def mark_uploaded(platform: str, filename: str):
    """예약된 항목을 업로드 완료(uploaded=True)로 표시한다. 없으면 무시(멱등)."""
    def _mark(index: dict):
        for f in index["files"]:
            if f["filename"] == filename:
                f["uploaded"] = True
                return

    update_index(platform, _mark)


# ── latest.json ─────────────────────────────────────────────────────────────

def get_latest(platform: str) -> dict | None:
    try:
        obj = _client().get_object(
            Bucket=settings.models_bucket,
            Key=_latest_key(platform),
        )
        data = json.loads(obj["Body"].read())
        if not data.get("version"):
            return None
        return data
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            return None
        raise


def put_latest(platform: str, data: dict):
    _client().put_object(
        Bucket=settings.models_bucket,
        Key=_latest_key(platform),
        Body=json.dumps(data, ensure_ascii=False, indent=2),
        ContentType="application/json",
    )


# ── 모델 버전 목록 ───────────────────────────────────────────────────────────

def list_model_versions(platform: str) -> list[str]:
    paginator = _client().get_paginator("list_objects_v2")
    pages = paginator.paginate(
        Bucket=settings.models_bucket,
        Prefix=f"{platform}/",
        Delimiter="/",
    )
    versions = []
    for page in pages:
        for prefix in page.get("CommonPrefixes", []):
            name = prefix["Prefix"].rstrip("/").split("/")[-1]
            if re.match(r"v\d+\.\d+", name):
                versions.append(name)
    return sorted(versions)


def next_version(platform: str) -> str:
    versions = list_model_versions(platform)
    if not versions:
        return "v1.0"
    major, minor = map(int, versions[-1][1:].split("."))
    return f"v{major}.{minor + 1}"


# ── Presigned URL ────────────────────────────────────────────────────────────

def generate_presigned_upload_url(platform: str, class_name: str, filename: str, expires: int = 300) -> str:
    return _client().generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.raw_data_bucket,
            "Key": _csv_key(platform, class_name, filename),
            "ContentType": "text/csv",
        },
        ExpiresIn=expires,
    )


# ── CSV 다운로드 ─────────────────────────────────────────────────────────────

def download_csv(platform: str, class_name: str, filename: str, local_path: str):
    _client().download_file(
        Bucket=settings.raw_data_bucket,
        Key=_csv_key(platform, class_name, filename),
        Filename=local_path,
    )


# ── 모델 업로드 ──────────────────────────────────────────────────────────────

def upload_model_artifact(platform: str, version: str, local_path: str, filename: str):
    _client().upload_file(
        Filename=local_path,
        Bucket=settings.models_bucket,
        Key=_model_key(platform, version, filename),
    )
