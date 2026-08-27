"""S3 인프라 계층 — 클라이언트, 키 조립, index.json ETag 낙관적 락 엔진.

각 도메인의 repository(app/{data,training,deployment}/repository.py)가 이 모듈 위에서
자기 도메인의 저장소 접근을 구현한다. 여기에는 도메인 규칙이 없다.
worker(별도 프로세스)는 web 도메인 패키지를 import하지 않으므로, worker가 쓰는
헬퍼(download_csv, upload_model_artifact, mark_trained)는 core에 둔다.
"""

import json
import time        # 충돌 재시도 백오프
from typing import Callable   # mutate 콜백 타입

import boto3                              # AWS SDK
from botocore.exceptions import ClientError   # S3 호출 에러(코드 분기에 사용)

from .config import settings

# index.json 조건부 쓰기(낙관적 락) 충돌 시 재시도 횟수
_INDEX_MAX_RETRIES = 5

_s3 = None   # boto3 클라이언트 캐시(지연 생성)

def _client():
    # boto3 S3 클라이언트를 한 번만 만들어 재사용(싱글톤).
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3", region_name=settings.aws_region)   # region 지정해 생성
    return _s3


# ── 키 조립 헬퍼 ─────────────────────────────────────────────────────────────
# S3 키(경로) 문자열을 한 곳에서 조립 → 규칙 일관성 유지.

def _index_key(platform: str) -> str:
    return f"{platform}/index.json"                       # 예: ios/index.json

def _uploads_index_key(platform: str) -> str:
    return f"{platform}/uploads-index.json"               # 유저 업로드 대장 (uploads 버킷)

def _upload_csv_key(platform: str, user_id: str, filename: str) -> str:
    # 유저별 prefix — 동의 철회 시 {platform}/{userId}/ 삭제로 정리 가능
    return f"{platform}/{user_id}/{filename}"             # 예: ios/user-1/SQUAT_user-1_0001.csv

def _csv_key(platform: str, class_name: str, filename: str) -> str:
    return f"{platform}/raw/{class_name}/{filename}"      # 예: ios/raw/SQUAT/SQUAT_xx_0001.csv

def _model_key(platform: str, version: str, filename: str) -> str:
    return f"{platform}/{version}/{filename}"             # 예: ios/v1.3/FitSet.mlpackage.zip

def _latest_key(platform: str) -> str:
    return f"{platform}/latest.json"                      # 예: ios/latest.json


# ── JSON 대장 엔진 — 학습 인덱스(index.json)와 업로드 대장(uploads-index.json)이 공유 ──

def _get_json_with_etag(bucket: str, key: str, empty: dict) -> tuple[dict, str | None]:
    """JSON 객체 본문과 ETag를 함께 읽는다. 없으면 (empty, None)."""
    # ETag = S3 객체의 버전 지문. 조건부 쓰기에서 "내가 읽은 그 버전 그대로인가" 확인에 쓴다.
    try:
        obj = _client().get_object(Bucket=bucket, Key=key)   # S3 GetObject
        return json.loads(obj["Body"].read()), obj["ETag"]   # (본문 dict, ETag)
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":       # 아직 파일이 없으면
            return empty, None                               # 빈 대장 반환
        raise


def _put_json(bucket: str, key: str, data: dict, *, etag: str | None):
    """JSON 객체를 조건부 저장한다 (_update_json 전용 내부 헬퍼).

    etag 있음  → IfMatch:    읽은 이후 다른 요청이 바꿨으면 412로 실패
    etag None  → IfNoneMatch: 그사이 다른 요청이 새로 만들었으면 412로 실패
    """
    # *: etag는 키워드 전용 인자. IfMatch/IfNoneMatch가 조건부 쓰기 헤더.
    extra = {"IfMatch": etag} if etag is not None else {"IfNoneMatch": "*"}

    _client().put_object(                     # S3 PutObject(조건부)
        Bucket=bucket,
        Key=key,
        Body=json.dumps(data, ensure_ascii=False, indent=2),   # dict → JSON 바이트
        ContentType="application/json",
        **extra,                              # 조건 헤더 펼치기
    )


def _update_json(bucket: str, key: str, empty: dict, mutate: Callable[[dict], None]) -> dict:
    """JSON 대장을 원자적으로 read-modify-write 한다.

    여러 요청이 동시에 같은 대장을 갱신해도 lost update가 나지 않도록 ETag 기반
    조건부 쓰기로 보호한다. 그사이 다른 요청이 대장을 바꿔 쓰기가 거부되면(412/409),
    최신본을 다시 읽어 mutate를 재적용하고 재시도한다.

    mutate(data)는 dict를 제자리(in-place)에서 변경하는 콜백.
    """
    for attempt in range(_INDEX_MAX_RETRIES):
        data, etag = _get_json_with_etag(bucket, key, empty)   # 최신본 + ETag 읽기
        mutate(data)                                           # 콜백이 data를 제자리 수정
        try:
            _put_json(bucket, key, data, etag=etag)            # 읽은 ETag 조건으로 저장 시도
            return data                                        # 성공 → 변경된 대장 반환
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("PreconditionFailed", "ConditionalRequestConflict"):
                # 동시 쓰기 충돌 → 살짝 백오프 후 최신본으로 재시도
                time.sleep(0.05 * (attempt + 1))               # 점증 백오프
                continue
            raise                                              # 그 외 에러는 전파

    raise RuntimeError(f"JSON 대장 동시 갱신 재시도 초과: {bucket}/{key}")   # 5회 실패


# ── 학습 인덱스(index.json, 신뢰 영역) ───────────────────────────────────────

def get_index(platform: str) -> dict:
    # 외부에 공개된 단순 조회(ETag 버림). data·training 도메인이 사용.
    data, _ = _get_json_with_etag(
        settings.raw_data_bucket, _index_key(platform), {"platform": platform, "files": []}
    )
    return data


def update_index(platform: str, mutate: Callable[[dict], None]) -> dict:
    # 학습 인덱스의 원자적 갱신 — 엔진은 _update_json이 정본
    return _update_json(
        settings.raw_data_bucket, _index_key(platform),
        {"platform": platform, "files": []}, mutate,
    )


# ── 업로드 대장(uploads-index.json, 격리 영역) ───────────────────────────────

def get_uploads_index(platform: str) -> dict:
    # 유저 자동수집 업로드 대장 조회 — data 도메인·승격 플로우가 사용
    data, _ = _get_json_with_etag(
        settings.user_uploads_bucket, _uploads_index_key(platform),
        {"platform": platform, "uploads": []},
    )
    return data


def update_uploads_index(platform: str, mutate: Callable[[dict], None]) -> dict:
    # 업로드 대장의 원자적 갱신 — 학습 인덱스와 같은 ETag 낙관적 락 엔진 사용
    return _update_json(
        settings.user_uploads_bucket, _uploads_index_key(platform),
        {"platform": platform, "uploads": []}, mutate,
    )


# ── worker 전용 헬퍼 (worker→core 단방향 의존을 지키기 위해 core에 둔다) ──────

def mark_trained(platform: str, filenames: list[str], version: str):
    # trainer.py 마지막 단계: 학습에 쓴 파일들의 trainedInVersion을 version으로 기록.
    name_set = set(filenames)

    def _mark(index: dict):                # update_index에 넘길 변경 콜백
        for f in index["files"]:
            if f["filename"] in name_set:
                f["trainedInVersion"] = version

    update_index(platform, _mark)


def download_csv(platform: str, class_name: str, filename: str, local_path: str):
    # trainer.py가 사용. S3의 CSV를 로컬 임시파일(local_path)로 내려받는다.
    _client().download_file(
        Bucket=settings.raw_data_bucket,
        Key=_csv_key(platform, class_name, filename),
        Filename=local_path,
    )


def upload_model_artifact(platform: str, version: str, local_path: str, filename: str):
    # trainer.py가 사용. 로컬 산출물(local_path)을 models_bucket의 {platform}/{version}/{filename}로 올린다.
    _client().upload_file(
        Filename=local_path,
        Bucket=settings.models_bucket,
        Key=_model_key(platform, version, filename),
    )
