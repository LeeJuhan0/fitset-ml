"""app.core.s3 의 순수 로직 단위 테스트 (boto3 클라이언트는 가짜로 대체).

플랫폼별 S3 키 조립 규칙과 버전 파싱/증가 로직은 플랫폼 엄격 분리의 핵심이므로
외부 의존 없이 직접 검증한다."""

import json

import pytest
from botocore.exceptions import ClientError

import app.core.s3 as s3


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


# ── next_version / 버전 파싱 ─────────────────────────────────────────────────

def test_next_version_empty_starts_at_v1_0(monkeypatch):
    monkeypatch.setattr(s3, "list_model_versions", lambda p: [])
    assert s3.next_version("ios") == "v1.0"


def test_next_version_increments_minor(monkeypatch):
    monkeypatch.setattr(s3, "list_model_versions", lambda p: ["v1.0", "v1.1", "v1.2"])
    assert s3.next_version("ios") == "v1.3"


def test_next_version_uses_latest_sorted(monkeypatch):
    monkeypatch.setattr(s3, "list_model_versions", lambda p: ["v1.0", "v1.9"])
    assert s3.next_version("android") == "v1.10"


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
    assert s3.list_model_versions("ios") == ["v1.0", "v1.2"]


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
