"""S3 저장 계층 단위 테스트 (boto3 클라이언트는 가짜로 대체).

인프라 엔진(app.core.s3)과 도메인 repository(deployment=latest 캐시·presign,
training=버전 채번)를 함께 검증한다. repository들은 core.s3._client()를 모듈 참조로
쓰므로, s3._client 하나만 가짜로 갈아끼우면 전부 통제된다."""

import json

import pytest
from botocore.exceptions import ClientError

import app.core.s3 as s3
import app.deployment.repository as dep_repo
import app.training.repository as train_repo


class _Body:
    """boto3 get_object 의 StreamingBody 흉내 — read() 로 본문 반환."""

    def __init__(self, payload: str):
        self._payload = payload

    def read(self):
        return self._payload


# ── 키 조립 헬퍼 ──────────────────────────────────────────────────────────────

def test_key_builders():
    assert s3._index_key("ios") == "ios/index.json"
    assert s3._csv_key("android", "SQUAT", "a.csv") == "android/raw/SQUAT/a.csv"
    assert s3._model_key("ios", "v1.3", "FitSet.mlpackage") == "ios/v1.3/FitSet.mlpackage"
    assert s3._latest_key("android") == "android/latest.json"


# ── latest.json 캐시 ─────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_latest_cache():
    # 테스트 간 캐시 오염 방지
    dep_repo._latest_cache.clear()
    yield
    dep_repo._latest_cache.clear()


class _CountingLatestClient:
    """get_object 호출 횟수를 세는 가짜 S3 클라이언트."""

    def __init__(self, payload: dict):
        self.payload = payload
        self.get_calls = 0
        self.put_calls = 0

    def get_object(self, **kwargs):
        self.get_calls += 1
        return {"Body": _Body(json.dumps(self.payload))}

    def put_object(self, **kwargs):
        self.put_calls += 1


def test_get_latest_caches_within_ttl(monkeypatch):
    fake = _CountingLatestClient({"version": "v1.0", "modelUrl": "s3://m/x"})
    monkeypatch.setattr(s3, "_client", lambda: fake)

    assert dep_repo.get_latest("ios")["version"] == "v1.0"
    assert dep_repo.get_latest("ios")["version"] == "v1.0"
    assert fake.get_calls == 1   # 두 번째는 캐시 히트 → S3 안 감


def test_get_latest_refetches_after_ttl(monkeypatch):
    fake = _CountingLatestClient({"version": "v1.0", "modelUrl": "s3://m/x"})
    monkeypatch.setattr(s3, "_client", lambda: fake)

    dep_repo.get_latest("ios")
    # 읽은 시각을 TTL 이전으로 되돌려 만료 상황을 만든다
    ts, data = dep_repo._latest_cache["ios"]
    dep_repo._latest_cache["ios"] = (ts - dep_repo._LATEST_TTL_SECONDS - 1, data)

    dep_repo.get_latest("ios")
    assert fake.get_calls == 2   # 만료 → S3 재조회


def test_put_latest_write_through(monkeypatch):
    fake = _CountingLatestClient({"version": "v1.0", "modelUrl": "s3://m/x"})
    monkeypatch.setattr(s3, "_client", lambda: fake)

    dep_repo.put_latest("ios", {"version": "v2.0", "modelUrl": "s3://m/y"})
    assert fake.put_calls == 1
    # 배포 직후 조회는 S3 안 가고 새 버전을 즉시 반환
    assert dep_repo.get_latest("ios")["version"] == "v2.0"
    assert fake.get_calls == 0


def test_get_latest_caches_none_and_platforms_isolated(monkeypatch):
    fake = _CountingLatestClient({"version": None})   # 구스키마/미배포
    monkeypatch.setattr(s3, "_client", lambda: fake)

    assert dep_repo.get_latest("ios") is None
    assert dep_repo.get_latest("ios") is None
    assert fake.get_calls == 1   # None 결과도 캐시

    dep_repo.get_latest("android")     # 다른 플랫폼은 별도 엔트리
    assert fake.get_calls == 2


# ── presigned 모델 다운로드 URL ──────────────────────────────────────────────

def test_generate_presigned_model_download_url_parses_s3_url(monkeypatch):
    captured = {}

    class _FakeClient:
        def generate_presigned_url(self, op, Params, ExpiresIn):
            captured.update(op=op, params=Params, expires=ExpiresIn)
            return "https://signed.example/x"

    monkeypatch.setattr(s3, "_client", lambda: _FakeClient())
    url = dep_repo.generate_presigned_model_download_url("s3://fitset-models/ios/v1.3/FitSet.mlpackage.zip")

    assert url == "https://signed.example/x"
    assert captured["op"] == "get_object"
    assert captured["params"] == {"Bucket": "fitset-models", "Key": "ios/v1.3/FitSet.mlpackage.zip"}
    assert captured["expires"] == 3600


# ── next_version / 버전 파싱 ─────────────────────────────────────────────────

def test_next_version_empty_starts_at_v1_0(monkeypatch):
    monkeypatch.setattr(train_repo, "list_model_versions", lambda p: [])
    assert train_repo.next_version("ios") == "v1.0"


def test_next_version_increments_minor(monkeypatch):
    monkeypatch.setattr(train_repo, "list_model_versions", lambda p: ["v1.0", "v1.1", "v1.2"])
    assert train_repo.next_version("ios") == "v1.3"


def test_next_version_uses_latest_sorted(monkeypatch):
    monkeypatch.setattr(train_repo, "list_model_versions", lambda p: ["v1.0", "v1.9"])
    assert train_repo.next_version("android") == "v1.10"


class _FakePaginator:
    def __init__(self, prefixes):
        self._prefixes = prefixes

    def paginate(self, **kwargs):
        return [{"CommonPrefixes": [{"Prefix": p} for p in self._prefixes]}]


def test_list_model_versions_filters_non_version_prefixes(monkeypatch):
    prefixes = ["ios/v1.0/", "ios/v1.2/", "ios/latest.json", "ios/mlflow/"]

    class _FakeClient:
        def get_paginator(self, _):
            return _FakePaginator(prefixes)

    monkeypatch.setattr(s3, "_client", lambda: _FakeClient())
    assert train_repo.list_model_versions("ios") == ["v1.0", "v1.2"]


# ── get_index: NoSuchKey 시 빈 인덱스 폴백 ────────────────────────────────────

def _no_such_key_error():
    return ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")


def test_get_index_returns_empty_on_missing(monkeypatch):
    class _FakeClient:
        def get_object(self, **kwargs):
            raise _no_such_key_error()

    monkeypatch.setattr(s3, "_client", lambda: _FakeClient())
    assert s3.get_index("ios") == {"platform": "ios", "files": []}


def test_get_index_reraises_other_errors(monkeypatch):
    class _FakeClient:
        def get_object(self, **kwargs):
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")

    monkeypatch.setattr(s3, "_client", lambda: _FakeClient())
    with pytest.raises(ClientError):
        s3.get_index("ios")


# ── mark_trained: 선택 파일만 trainedInVersion 갱신 ───────────────────────────

def test_mark_trained_updates_only_selected(monkeypatch):
    index = {
        "platform": "ios",
        "files": [
            {"filename": "a.csv", "trainedInVersion": None},
            {"filename": "b.csv", "trainedInVersion": None},
            {"filename": "c.csv", "trainedInVersion": "v1.0"},
        ],
    }
    # update_index 의 원자성은 별도 테스트에서 검증하고, 여기선 mutate 로직만 본다.
    saved = {}

    def _fake_update(platform, mutate):
        mutate(index)
        saved["data"] = index

    monkeypatch.setattr(s3, "update_index", _fake_update)

    s3.mark_trained("ios", ["a.csv", "c.csv"], "v1.5")

    by_name = {f["filename"]: f["trainedInVersion"] for f in saved["data"]["files"]}
    assert by_name == {"a.csv": "v1.5", "b.csv": None, "c.csv": "v1.5"}


# ── update_index: ETag 낙관적 락 + 충돌 재시도 ────────────────────────────────

def _precondition_failed():
    return ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")


def test_update_index_uses_etag_for_conditional_write(monkeypatch):
    """기존 인덱스를 읽을 때 받은 ETag 가 put 의 IfMatch 로 전달돼야 한다."""
    puts = []

    class _FakeClient:
        def get_object(self, **kwargs):
            return {
                "Body": _Body(json.dumps({"platform": "ios", "files": []})),
                "ETag": '"abc123"',
            }

        def put_object(self, **kwargs):
            puts.append(kwargs)
            return {}

    monkeypatch.setattr(s3, "_client", lambda: _FakeClient())

    s3.update_index("ios", lambda idx: idx["files"].append({"filename": "x.csv"}))

    assert len(puts) == 1
    assert puts[0]["IfMatch"] == '"abc123"'
    assert "IfNoneMatch" not in puts[0]
    written = json.loads(puts[0]["Body"])
    assert written["files"][0]["filename"] == "x.csv"


def test_update_index_creates_with_if_none_match_when_absent(monkeypatch):
    """인덱스가 없으면 IfNoneMatch='*' 로 '없을 때만 생성' 조건을 건다."""
    puts = []

    class _FakeClient:
        def get_object(self, **kwargs):
            raise _no_such_key_error()

        def put_object(self, **kwargs):
            puts.append(kwargs)
            return {}

    monkeypatch.setattr(s3, "_client", lambda: _FakeClient())

    s3.update_index("ios", lambda idx: idx["files"].append({"filename": "x.csv"}))

    assert puts[0]["IfNoneMatch"] == "*"
    assert "IfMatch" not in puts[0]


def test_update_index_retries_then_succeeds_on_conflict(monkeypatch):
    """동시 쓰기로 412 가 나면 최신본을 다시 읽어 재시도하고, 갱신을 잃지 않는다."""
    monkeypatch.setattr(s3.time, "sleep", lambda _: None)  # 백오프 제거

    # 1차 put 은 그사이 b.csv 가 들어온 상태와 충돌(412), 2차에 성공.
    state = {"files": []}
    puts = {"n": 0}

    class _FakeClient:
        def get_object(self, **kwargs):
            return {
                "Body": _Body(json.dumps({"platform": "ios", "files": list(state["files"])})),
                "ETag": f'"etag-{len(state["files"])}"',
            }

        def put_object(self, **kwargs):
            puts["n"] += 1
            if puts["n"] == 1:
                # 첫 시도 전에 다른 요청이 b.csv 를 추가한 것으로 시뮬레이션
                state["files"].append({"filename": "b.csv"})
                raise _precondition_failed()
            state["files"] = json.loads(kwargs["Body"])["files"]
            return {}

    monkeypatch.setattr(s3, "_client", lambda: _FakeClient())

    s3.update_index("ios", lambda idx: idx["files"].append({"filename": "a.csv"}))

    names = {f["filename"] for f in state["files"]}
    assert names == {"a.csv", "b.csv"}  # 두 갱신 모두 보존
    assert puts["n"] == 2


def test_update_index_raises_after_max_retries(monkeypatch):
    monkeypatch.setattr(s3.time, "sleep", lambda _: None)

    class _FakeClient:
        def get_object(self, **kwargs):
            return {"Body": _Body(json.dumps({"platform": "ios", "files": []})), "ETag": '"e"'}

        def put_object(self, **kwargs):
            raise _precondition_failed()

    monkeypatch.setattr(s3, "_client", lambda: _FakeClient())

    with pytest.raises(RuntimeError):
        s3.update_index("ios", lambda idx: None)
