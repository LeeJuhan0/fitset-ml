# ─────────────────────────────────────────────────────────────────────────────
# deployment 도메인 Repository — latest.json 읽기/쓰기(+TTL 캐시), 모델 다운로드 URL 서명.
# core.s3(인프라 엔진) 위에서 이 도메인의 저장소 접근만 구현한다.
# ─────────────────────────────────────────────────────────────────────────────
import json
import time

from botocore.exceptions import ClientError

from app.core import s3

# 인메모리 캐시 — S3의 latest.json이 정본이고 여기는 TTL짜리 사본.
# 서버 시작 직후엔 비어 있으므로 첫 요청이 S3에서 읽어 채운다.
# 배포(put_latest)는 같은 프로세스를 지나가므로 write-through로 즉시 반영된다.
# 스레드 경합은 최악의 경우 S3를 한 번 더 읽을 뿐이라 락 없이 둔다.
_LATEST_TTL_SECONDS = 60
_latest_cache: dict[str, tuple[float, dict | None]] = {}   # platform -> (읽은 시각, 값)


def get_latest(platform: str) -> dict | None:
    # 배포된 최신 모델 정보(없으면 None).
    cached = _latest_cache.get(platform)
    if cached and time.time() - cached[0] < _LATEST_TTL_SECONDS:
        return cached[1]                  # TTL 이내면 S3 안 가고 사본 반환

    try:
        obj = s3._client().get_object(
            Bucket=s3.settings.models_bucket,
            Key=s3._latest_key(platform),
        )
        data = json.loads(obj["Body"].read())
        if not data.get("version"):   # 빈/무효 latest는 None 취급
            data = None
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchKey":
            raise                     # 조회 실패는 캐시하지 않고 전파
        data = None

    _latest_cache[platform] = (time.time(), data)   # "미배포(None)"도 캐시 대상
    return data


def put_latest(platform: str, data: dict):
    # 배포 정보를 latest.json에 덮어쓰기(조건 없음).
    s3._client().put_object(
        Bucket=s3.settings.models_bucket,
        Key=s3._latest_key(platform),
        Body=json.dumps(data, ensure_ascii=False, indent=2),
        ContentType="application/json",
    )
    _latest_cache[platform] = (time.time(), data)   # write-through — 다음 폴링부터 즉시 새 버전


def generate_presigned_model_download_url(model_url: str, expires: int = 3600) -> str:
    # latest.json의 s3:// 경로를 앱이 직접 GET할 수 있는 임시 서명 URL로 변환(버킷은 프라이빗 유지).
    bucket, key = model_url.removeprefix("s3://").split("/", 1)   # "s3://버킷/키" 분해
    return s3._client().generate_presigned_url(
        "get_object",           # 허용 동작: 다운로드(GET)
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires,      # 유효시간(초, 기본 3600)
    )
