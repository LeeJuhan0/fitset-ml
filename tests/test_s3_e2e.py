"""실제 AWS S3(임시 버킷) 위에서 index.json 동시성 보호를 검증하는 E2E 테스트.

unit(test_s3_helpers)은 우리가 짠 가짜 클라이언트의 대본을, integration(test_s3_integration)은
moto의 대본을 검증한다. 둘 다 시뮬레이션이다. 여기서는 진짜 S3 API에 boto3 로 붙어
ETag/IfMatch/IfNoneMatch 조건부 쓰기 위에서 update_index 의 read-modify-write 루프를
**실제 스레드 동시 실행**으로 돌린다. 대본이 아니라 현실에서 lost update 가 안 나는지 본다.

안전장치:
  - settings.raw_data_bucket 이 'fitset-citest' 로 시작할 때만 실행한다(아니면 모듈 통째로 skip).
    CI 는 매 잡마다 fitset-citest-<run_id> 임시 버킷을 만들어 RAW_DATA_BUCKET 로 주입하고,
    잡 종료 시 버킷을 삭제한다. 운영 버킷(fitset-dataset)은 절대 건드리지 않는다.

실행: RAW_DATA_BUCKET=fitset-citest-... pytest -m e2e
"""

import json
import threading
import time

import pytest

from app.core.config import settings

pytestmark = pytest.mark.e2e

# 운영 버킷 보호 — 임시 CI 버킷이 아니면 이 파일 전체를 건너뛴다.
if not settings.raw_data_bucket.startswith("fitset-citest"):
    pytest.skip(
        "E2E 는 임시 CI 버킷에서만 실행 (RAW_DATA_BUCKET=fitset-citest-*)",
        allow_module_level=True,
    )

import app.core.s3 as s3  # noqa: E402  (skip 가드 통과 후 import)

PLATFORM = "ios"


@pytest.fixture(autouse=True)
def _clean_index():
    """각 테스트 전후로 index.json 키를 비워 멱등하게 한다(버킷은 CI가 정리)."""
    s3._s3 = None  # 클라이언트 캐시 초기화

    def _rm():
        try:
            s3._client().delete_object(
                Bucket=settings.raw_data_bucket, Key=s3._index_key(PLATFORM)
            )
        except Exception:
            pass

    _rm()
    yield
    _rm()


def _read_files() -> list[dict]:
    return s3.get_index(PLATFORM).get("files", [])


def test_get_index_empty_when_absent_real_s3():
    # 객체 부재 시 NoSuchKey → 빈 인덱스 폴백 (실제 S3 에러 경로)
    assert s3.get_index(PLATFORM) == {"platform": PLATFORM, "files": []}


def test_concurrent_update_index_no_lost_update_real_s3():
    """4개 스레드가 동시에 같은 index.json 에 서로 다른 파일을 append.

    각 mutate 안에 짧은 sleep 을 넣어 read→write 윈도가 겹치게 만든다(락이 없으면
    lost update 가 거의 확정). 실제 S3 가 stale IfMatch 를 412 로 거부 → update_index 가
    최신본을 다시 읽어 재시도 → 4개 항목이 모두 보존돼야 한다.
    (_INDEX_MAX_RETRIES=5 이므로 4스레드는 worst-case 3회 재시도로 안전)
    """
    n = 4
    errors: list[Exception] = []

    def worker(i: int):
        def mutate(index: dict):
            index["files"].append({"filename": f"f{i}.csv", "class": "SQUAT"})
            time.sleep(0.1)  # read-modify-write 윈도를 넓혀 경합 유발

        try:
            s3.update_index(PLATFORM, mutate)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"동시 갱신 중 예외: {errors}"
    names = sorted(f["filename"] for f in _read_files())
    assert names == [f"f{i}.csv" for i in range(n)], (
        f"lost update 발생 — 기대 {n}개, 실제 {names}"
    )


def test_if_none_match_create_is_atomic_real_s3():
    """부재 상태에서 update_index 가 IfNoneMatch='*' 로 생성하고, 두 번째 호출은 append."""
    s3.update_index(PLATFORM, lambda i: i["files"].append({"filename": "a.csv"}))
    s3.update_index(PLATFORM, lambda i: i["files"].append({"filename": "b.csv"}))

    # 실제로 저장된 객체를 직접 읽어 본문 확인
    obj = s3._client().get_object(
        Bucket=settings.raw_data_bucket, Key=s3._index_key(PLATFORM)
    )
    files = json.loads(obj["Body"].read())["files"]
    assert sorted(f["filename"] for f in files) == ["a.csv", "b.csv"]
