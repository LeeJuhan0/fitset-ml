"""app.core.s3 의 index.json 동시성 보호를 **실제 S3 의미**로 검증하는 통합 테스트.

단위 테스트(test_s3_helpers)는 우리가 짠 가짜 클라이언트 위에서 돈다 — "IfMatch 를
넘기더라", "PreconditionFailed 면 재시도하더라" 같은 우리 로직은 검증하지만, 실제 S3 가
그 조건부 쓰기를 정말 그렇게 처리하는지는 검증하지 못한다. 대본이 현실과 다르면
테스트는 통과해도 운영에서 터진다.

여기서는 moto(S3 API 의미를 충실히 재현)를 실제 boto3 클라이언트로 띄워, get→mutate→
조건부 put 루프 전체를 진짜 ETag/IfMatch/IfNoneMatch 동작 위에서 돌린다.
"""

import json

import pytest

moto = pytest.importorskip("moto")  # moto 미설치 환경에서는 통합 테스트 스킵
from moto import mock_aws  # noqa: E402
import boto3  # noqa: E402

import app.core.s3 as s3  # noqa: E402
import app.data.repository as data_repo  # noqa: E402
from app.core.config import settings  # noqa: E402


@pytest.fixture
def s3_backed(monkeypatch):
    """moto S3 위에서 raw_data_bucket 을 만들고, s3._client 캐시를 초기화한다."""
    with mock_aws():
        client = boto3.client("s3", region_name=settings.aws_region)
        client.create_bucket(
            Bucket=settings.raw_data_bucket,
            CreateBucketConfiguration={"LocationConstraint": settings.aws_region},
        )
        client.create_bucket(   # 유저 업로드 격리 버킷 — uploads-index.json이 여기 산다
            Bucket=settings.user_uploads_bucket,
            CreateBucketConfiguration={"LocationConstraint": settings.aws_region},
        )
        # s3 모듈은 전역 _s3 를 캐시하므로 테스트마다 비워 moto 클라이언트를 새로 잡게 한다.
        monkeypatch.setattr(s3, "_s3", None)
        yield client


def _read(client) -> dict:
    obj = client.get_object(Bucket=settings.raw_data_bucket, Key="ios/index.json")
    return json.loads(obj["Body"].read())


def _read_uploads(client) -> dict:
    obj = client.get_object(Bucket=settings.user_uploads_bucket, Key="ios/uploads-index.json")
    return json.loads(obj["Body"].read())


def test_get_index_empty_when_absent(s3_backed):
    # 객체가 없으면 NoSuchKey → 빈 인덱스 폴백 (실제 S3 에러 경로)
    assert s3.get_index("ios") == {"platform": "ios", "files": []}


def test_update_index_creates_then_appends(s3_backed):
    s3.update_index("ios", lambda i: i["files"].append({"filename": "a.csv"}))
    s3.update_index("ios", lambda i: i["files"].append({"filename": "b.csv"}))

    names = [f["filename"] for f in _read(s3_backed)["files"]]
    assert names == ["a.csv", "b.csv"]


def test_reserve_user_upload_assigns_sequential_names(s3_backed):
    # 같은 class+userId → 순번 증가, 다른 userId → 별도 순번 (채번 주인 = 토큰 userId)
    f1 = data_repo.reserve_user_upload("ios", "SQUAT", "user1", "DEV1")
    f2 = data_repo.reserve_user_upload("ios", "SQUAT", "user1", "DEV1")
    f3 = data_repo.reserve_user_upload("ios", "SQUAT", "user2", "DEV1")
    assert f1 == "SQUAT_user1_0001.csv"
    assert f2 == "SQUAT_user1_0002.csv"
    assert f3 == "SQUAT_user2_0001.csv"

    entry = next(f for f in _read_uploads(s3_backed)["uploads"] if f["filename"] == f1)
    assert entry["uploaded"] is False           # 예약 상태
    assert entry["status"] == "pending"         # 승격 전 격리 상태
    assert entry["userId"] == "user1"
    assert entry["deviceId"] == "DEV1"          # 기기 구분 메타


def test_mark_user_uploaded_flips_flag(s3_backed):
    fn = data_repo.reserve_user_upload("ios", "PUSHUP", "user1", "DEV1")
    data_repo.mark_user_uploaded("ios", fn)
    entry = next(f for f in _read_uploads(s3_backed)["uploads"] if f["filename"] == fn)
    assert entry["uploaded"] is True
    assert entry["status"] == "pending"         # 업로드 확정은 승격이 아니다


def test_reserve_user_upload_concurrent_no_duplicate_numbers(s3_backed):
    """동시 예약 — 실제 S3(moto) 조건부 쓰기 위에서 번호 중복이 없어야 한다."""
    import threading

    names: list[str] = []
    lock = threading.Lock()

    def worker():
        fn = data_repo.reserve_user_upload("ios", "REST", "user1", "DEV1")
        with lock:
            names.append(fn)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(set(names)) == 4  # 4개 모두 고유
    assert sorted(names) == [f"REST_user1_000{i}.csv" for i in range(1, 5)]


def test_update_index_survives_real_concurrent_write(s3_backed):
    """update_index 가 ETag 를 읽은 뒤, put 전에 다른 요청이 인덱스를 바꾼 상황.

    실제 S3(moto)가 stale IfMatch 를 412 로 거부 → update_index 가 최신본을 다시 읽어
    재시도 → 두 갱신이 모두 보존되는지 확인한다. 가짜가 아니라 진짜 조건부 쓰기 위에서.
    """
    # 인덱스를 먼저 하나 만들어 둔다.
    s3.update_index("ios", lambda i: i["files"].append({"filename": "base.csv"}))

    fired = {"done": False}

    def mutate(index):
        index["files"].append({"filename": "mine.csv"})
        # 첫 시도에서만: ETag 를 읽은 직후 다른 요청이 끼어들어 인덱스를 바꾼 것으로 시뮬레이션.
        # (update_index 내부 put 은 이제 stale ETag 라 실제로 412 를 맞는다)
        if not fired["done"]:
            fired["done"] = True
            current = _read(s3_backed)
            current["files"].append({"filename": "intruder.csv"})
            s3_backed.put_object(
                Bucket=settings.raw_data_bucket,
                Key="ios/index.json",
                Body=json.dumps(current),
            )

    s3.update_index("ios", mutate)

    names = {f["filename"] for f in _read(s3_backed)["files"]}
    # intruder(끼어든 쓰기)도, mine(재시도된 내 쓰기)도 모두 살아있어야 한다.
    assert names == {"base.csv", "intruder.csv", "mine.csv"}


def test_concurrent_create_only_one_wins_then_merges(s3_backed):
    """둘 다 '인덱스 없음'을 보고 IfNoneMatch='*' 로 생성 시도하는 경합.

    하나는 생성 성공, 다른 하나는 412 로 거부된 뒤 최신본을 읽어 자기 항목을 합쳐야 한다.
    """
    fired = {"done": False}

    def mutate(index):
        index["files"].append({"filename": "mine.csv"})
        if not fired["done"]:
            fired["done"] = True
            # 내가 put 하기 직전에 다른 요청이 먼저 인덱스를 만들어 버림
            s3_backed.put_object(
                Bucket=settings.raw_data_bucket,
                Key="ios/index.json",
                Body=json.dumps({"platform": "ios", "files": [{"filename": "other.csv"}]}),
            )

    s3.update_index("ios", mutate)

    names = {f["filename"] for f in _read(s3_backed)["files"]}
    assert names == {"other.csv", "mine.csv"}


def test_reserve_admin_upload_uses_dataset_index(s3_backed):
    # 어드민 직행 — 학습 인덱스(index.json)에 예약되고 deviceId 기준으로 채번된다
    f1 = data_repo.reserve_admin_upload("ios", "SQUAT", "DEV1")
    f2 = data_repo.reserve_admin_upload("ios", "SQUAT", "DEV1")
    assert [f1, f2] == ["SQUAT_DEV1_0001.csv", "SQUAT_DEV1_0002.csv"]

    entry = next(f for f in _read(s3_backed)["files"] if f["filename"] == f1)
    assert entry["uploaded"] is False
    assert entry["trainedInVersion"] is None

    data_repo.mark_admin_uploaded("ios", f1)
    entry = next(f for f in _read(s3_backed)["files"] if f["filename"] == f1)
    assert entry["uploaded"] is True
