"""S3 스토리지 — fitset-raw-data(학습 데이터) / fitset-models(모델 아티팩트)"""

import json
import re
import boto3
from botocore.exceptions import ClientError

from .config import settings

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

def get_index(platform: str) -> dict:
    try:
        obj = _client().get_object(
            Bucket=settings.raw_data_bucket,
            Key=_index_key(platform),
        )
        return json.loads(obj["Body"].read())
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            return {"platform": platform, "files": []}
        raise


def put_index(platform: str, data: dict):
    _client().put_object(
        Bucket=settings.raw_data_bucket,
        Key=_index_key(platform),
        Body=json.dumps(data, ensure_ascii=False, indent=2),
        ContentType="application/json",
    )


def mark_trained(platform: str, filenames: list[str], version: str):
    index = get_index(platform)
    name_set = set(filenames)
    for f in index["files"]:
        if f["filename"] in name_set:
            f["trainedInVersion"] = version
    put_index(platform, index)


# ── latest.json ─────────────────────────────────────────────────────────────

def get_latest(platform: str) -> dict | None:
    try:
        obj = _client().get_object(
            Bucket=settings.models_bucket,
            Key=_latest_key(platform),
        )
        return json.loads(obj["Body"].read())
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
