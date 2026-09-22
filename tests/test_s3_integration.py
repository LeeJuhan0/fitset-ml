import pytest

moto = pytest.importorskip("moto")
from moto import mock_aws
import boto3

import app.core.s3 as s3
from app.core.config import settings

BUCKETS = ("collect_imu_bucket", "collect_video_bucket", "collect_labeled_bucket")


@pytest.fixture
def s3_backed(monkeypatch):
    """moto S3 위에서 수집·영상·라벨 버킷을 만들고, s3._client 캐시를 초기화한다"""
    with mock_aws():
        client = boto3.client("s3", region_name=settings.aws_region)
        for name in BUCKETS:
            client.create_bucket(
                Bucket=getattr(settings, name),
                CreateBucketConfiguration={"LocationConstraint": settings.aws_region},
            )
        monkeypatch.setattr(s3, "_s3", None)
        yield client


def test_upload_copy_delete_roundtrip(s3_backed, tmp_path):
    src = tmp_path / "a.csv"
    src.write_text("timestamp,ax\n1,2\n")
    key = s3._collect_key("ios", "PUSHUP", "a.csv")

    s3.upload_object(settings.collect_imu_bucket, key, str(src), "text/csv")
    head = s3_backed.head_object(Bucket=settings.collect_imu_bucket, Key=key)
    assert head["ContentType"] == "text/csv"

    s3.copy_object(settings.collect_imu_bucket, key, settings.collect_labeled_bucket)
    assert s3.get_object_bytes(settings.collect_labeled_bucket, key) == b"timestamp,ax\n1,2\n"

    s3.delete_object(settings.collect_imu_bucket, key)
    listed = s3_backed.list_objects_v2(Bucket=settings.collect_imu_bucket)
    assert listed.get("KeyCount", 0) == 0

    out = tmp_path / "b.csv"
    s3.download_object(settings.collect_labeled_bucket, key, str(out))
    assert out.read_text() == "timestamp,ax\n1,2\n"


def test_presigned_urls_point_at_bucket_and_key(s3_backed):
    key = s3._collect_key("ios", "PUSHUP", "a.mov")
    put = s3.presigned_put_url(settings.collect_video_bucket, key, "video/quicktime", 60)
    get = s3.presigned_get_url(settings.collect_video_bucket, key, 60)
    assert settings.collect_video_bucket in put and key in put
    assert settings.collect_video_bucket in get and key in get
