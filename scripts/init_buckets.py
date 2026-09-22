import argparse

import boto3

from app.core.config import PLATFORMS, settings
from app.core.s3 import _S3_CONFIG
from app.exercises.service import load_mapping
from app.exercises.utils import class_folder


def main():
    """5개 버킷에 플랫폼별·종목별(인덱스 순) 폴더 객체 생성, dataset 은 raw/ 아래, 멱등"""
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=None, help="class-mapping.json 위치, 기본 CLASS_MAPPING_URL")
    args = ap.parse_args()
    classes = load_mapping(args.source)["classes"]
    client = boto3.client("s3", region_name=settings.aws_region, config=_S3_CONFIG)
    buckets = [(settings.collect_imu_bucket, ""), (settings.collect_video_bucket, ""), (settings.collect_labeled_bucket, ""),
               (settings.phase_models_bucket, ""), (settings.raw_data_bucket, "raw/")]
    created = 0
    for bucket, prefix in buckets:
        for platform in sorted(PLATFORMS):
            for it in sorted(classes, key=lambda c: c["index"]):
                client.put_object(Bucket=bucket, Key=f"{platform}/{prefix}{class_folder(it['index'], it['class'])}/", Body=b"")
                created += 1
    print(f"folders {created} across {len(buckets)} buckets, {len(classes)} classes x {len(PLATFORMS)} platforms")


if __name__ == "__main__":
    main()
