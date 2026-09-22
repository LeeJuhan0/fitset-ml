import json
import time

from botocore.exceptions import ClientError

from app.core import s3

_LATEST_TTL_SECONDS = 60
_latest_cache: dict[str, tuple[float, dict | None]] = {}


def get_latest(platform: str) -> dict | None:
    """latest.json 조회, TTL 캐시"""
    cached = _latest_cache.get(platform)
    if cached and time.time() - cached[0] < _LATEST_TTL_SECONDS:
        return cached[1]

    try:
        obj = s3._client().get_object(
            Bucket=s3.settings.models_bucket,
            Key=s3._latest_key(platform),
        )
        data = json.loads(obj["Body"].read())
        if not data.get("version"):
            data = None
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchKey":
            raise
        data = None

    _latest_cache[platform] = (time.time(), data)
    return data


def put_latest(platform: str, data: dict):
    """latest.json 저장, 캐시 write-through"""
    s3._client().put_object(
        Bucket=s3.settings.models_bucket,
        Key=s3._latest_key(platform),
        Body=json.dumps(data, ensure_ascii=False, indent=2),
        ContentType="application/json",
    )
    _latest_cache[platform] = (time.time(), data)


def generate_presigned_model_download_url(model_url: str, expires: int = 3600) -> str:
    """s3 경로 → GET 서명 URL"""
    bucket, key = model_url.removeprefix("s3://").split("/", 1)
    return s3._client().generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires,
    )
