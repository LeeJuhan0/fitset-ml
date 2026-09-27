import json
import time

from botocore.exceptions import ClientError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import s3
from app.core.models import Platform, ensure_platform
from app.deployment.models import ModelDeployment

_LATEST_TTL_SECONDS = 60
_latest_cache: dict[str, tuple[float, dict | None]] = {}


def get_latest(platform: str) -> dict | None:
    """latest.json 조회, TTL 캐시"""
    cached = _latest_cache.get(platform)
    if cached and time.time() - cached[0] < _LATEST_TTL_SECONDS:
        return cached[1]

    try:
        obj = s3.client().get_object(
            Bucket=s3.settings.models_bucket,
            Key=s3.latest_key(platform),
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
    s3.client().put_object(
        Bucket=s3.settings.models_bucket,
        Key=s3.latest_key(platform),
        Body=json.dumps(data, ensure_ascii=False, indent=2),
        ContentType="application/json",
    )
    _latest_cache[platform] = (time.time(), data)


def generate_presigned_model_download_url(model_url: str, expires: int = 3600) -> str:
    """s3 경로 → GET 서명 URL"""
    bucket, key = model_url.removeprefix("s3://").split("/", 1)
    return s3.client().generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires,
    )


async def add_deployment(s: AsyncSession, platform: str, **fields) -> None:
    """배포 이력 한 행 기록"""
    row = ModelDeployment(platform=await ensure_platform(s, platform), **fields)
    s.add(row)
    await s.flush()


async def latest_deployments(s: AsyncSession, platform: str) -> list[ModelDeployment]:
    """종류와 종목별 가장 최근 배포 행"""
    rows = (await s.exec(
        select(ModelDeployment).join(Platform).where(Platform.name == platform)
        .order_by(col(ModelDeployment.created_at).desc(), col(ModelDeployment.id).desc())
    )).all()
    latest: dict[tuple, ModelDeployment] = {}
    for r in rows:
        latest.setdefault((r.kind, r.class_name), r)
    return list(latest.values())
