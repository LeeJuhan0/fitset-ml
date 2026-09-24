import boto3
from botocore.config import Config

from .config import settings

_S3_CONFIG = Config(s3={"addressing_style": "virtual"})

_s3 = None

def client():
    """boto3 S3 클라이언트 싱글톤, virtual-host 주소"""
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3", region_name=settings.aws_region, config=_S3_CONFIG)
    return _s3


def csv_key(platform: str, folder: str, filename: str) -> str:
    """dataset raw 키 조립, folder 는 {index:03d}_{CLASS}, 구 데이터는 CLASS"""
    return f"{platform}/raw/{folder}/{filename}"

def model_key(platform: str, version: str, filename: str) -> str:
    """모델 산출물 키 조립"""
    return f"{platform}/{version}/{filename}"

def latest_key(platform: str) -> str:
    """latest.json 키"""
    return f"{platform}/latest.json"

def collect_key(platform: str, folder: str, filename: str) -> str:
    """수집·라벨·모델 버킷 키 조립, folder 는 {index:03d}_{CLASS}"""
    return f"{platform}/{folder}/{filename}"


def upload_model_artifact(platform: str, version: str, local_path: str, filename: str):
    """모델 산출물 업로드"""
    client().upload_file(
        Filename=local_path,
        Bucket=settings.models_bucket,
        Key=model_key(platform, version, filename),
    )


def download_object(bucket: str, key: str, local_path: str):
    """객체 로컬 다운로드"""
    client().download_file(Bucket=bucket, Key=key, Filename=local_path)


def upload_object(bucket: str, key: str, local_path: str, content_type: str):
    """로컬 파일 업로드, Content-Type 지정"""
    client().upload_file(Filename=local_path, Bucket=bucket, Key=key, ExtraArgs={"ContentType": content_type})


def get_object_bytes(bucket: str, key: str) -> bytes:
    """객체 본문 메모리 읽기"""
    return client().get_object(Bucket=bucket, Key=key)["Body"].read()


def copy_object(src_bucket: str, key: str, dst_bucket: str, dst_key: str | None = None):
    """버킷 간 복사, 대상 키 지정 가능"""
    client().copy_object(Bucket=dst_bucket, Key=dst_key or key, CopySource={"Bucket": src_bucket, "Key": key})


def delete_object(bucket: str, key: str):
    """객체 삭제"""
    client().delete_object(Bucket=bucket, Key=key)


def presigned_put_url(bucket: str, key: str, content_type: str, expires: int) -> str:
    """PUT 서명 URL"""
    return client().generate_presigned_url(
        "put_object", Params={"Bucket": bucket, "Key": key, "ContentType": content_type}, ExpiresIn=expires,
    )


def presigned_get_url(bucket: str, key: str, expires: int) -> str:
    """GET 서명 URL"""
    return client().generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires)
