import argparse
import json

from botocore.exceptions import ClientError
from sqlmodel import select

from app.core import db, s3
from app.core.config import PLATFORMS, settings
from app.core.models import ensure_device, ensure_platform, find_exercise
from app.core.utils import parse_iso
from app.data.models import DatasetFile


def read_json(bucket: str, key: str) -> dict | None:
    """S3 JSON 객체 읽기, 없으면 None"""
    try:
        return json.loads(s3.get_object_bytes(bucket, key))
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            return None
        raise


async def migrate_dataset(s, platform: str) -> int:
    """index.json → dataset_files, 중복 건너뜀"""
    index = read_json(settings.raw_data_bucket, f"{platform}/index.json")
    if index is None:
        return 0
    added = 0
    p = await ensure_platform(s, platform)
    existing = set((await s.exec(select(DatasetFile.filename).where(DatasetFile.platform_id == p.id))).all())
    for f in index.get("files", []):
        if f["filename"] in existing:
            continue
        s.add(DatasetFile(
            platform=p,
            device=await ensure_device(s, p, f.get("deviceId") or f.get("userId") or "unknown"),
            exercise=await find_exercise(s, f["class"]),
            filename=f["filename"],
            class_name=f["class"],
            bucket=settings.raw_data_bucket,
            s3_key=s3._csv_key(platform, f["class"], f["filename"]),
            uploaded=bool(f.get("uploaded", True)),
            trained_in_version=f.get("trainedInVersion"),
            created_at=parse_iso(f.get("collectedAt")),
        ))
        added += 1
    return added


def main():
    """플랫폼별 이관 실행, 결과 출력"""
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", choices=sorted(PLATFORMS), help="없으면 전체 플랫폼")
    args = ap.parse_args()
    async def go():
        """테이블 생성 후 플랫폼별 이관"""
        await db.init_db()
        for platform in ([args.platform] if args.platform else sorted(PLATFORMS)):
            async with db.session() as s:
                print(f"{platform}: dataset_files +{await migrate_dataset(s, platform)}")

    db.run(go())


if __name__ == "__main__":
    main()
