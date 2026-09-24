import json

import pytest

import app.core.s3 as s3
import app.deployment.repository as dep_repo
import app.training.repository as train_repo


class _Body:
    """boto3 get_object 의 StreamingBody 흉내 — read() 로 본문 반환"""

    def __init__(self, payload: str):
        self._payload = payload

    def read(self):
        return self._payload


def test_key_builders():
    assert s3.csv_key("android", "SQUAT", "a.csv") == "android/raw/SQUAT/a.csv"
    assert s3.model_key("ios", "v1.3", "FitSet.mlpackage") == "ios/v1.3/FitSet.mlpackage"
    assert s3.latest_key("android") == "android/latest.json"
    assert s3.collect_key("ios", "001_PUSHUP", "PUSHUP_DEV_0001.mov") == "ios/001_PUSHUP/PUSHUP_DEV_0001.mov"


@pytest.fixture(autouse=True)
def clear_latest_cache():
    dep_repo._latest_cache.clear()
    yield
    dep_repo._latest_cache.clear()


class _CountingLatestClient:
    """get_object 호출 횟수를 세는 가짜 S3 클라이언트"""

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
    monkeypatch.setattr(s3, "client", lambda: fake)

    assert dep_repo.get_latest("ios")["version"] == "v1.0"
    assert dep_repo.get_latest("ios")["version"] == "v1.0"
    assert fake.get_calls == 1


def test_get_latest_refetches_after_ttl(monkeypatch):
    fake = _CountingLatestClient({"version": "v1.0", "modelUrl": "s3://m/x"})
    monkeypatch.setattr(s3, "client", lambda: fake)

    dep_repo.get_latest("ios")
    ts, data = dep_repo._latest_cache["ios"]
    dep_repo._latest_cache["ios"] = (ts - dep_repo._LATEST_TTL_SECONDS - 1, data)

    dep_repo.get_latest("ios")
    assert fake.get_calls == 2


def test_put_latest_write_through(monkeypatch):
    fake = _CountingLatestClient({"version": "v1.0", "modelUrl": "s3://m/x"})
    monkeypatch.setattr(s3, "client", lambda: fake)

    dep_repo.put_latest("ios", {"version": "v2.0", "modelUrl": "s3://m/y"})
    assert fake.put_calls == 1
    assert dep_repo.get_latest("ios")["version"] == "v2.0"
    assert fake.get_calls == 0


def test_get_latest_caches_none_and_platforms_isolated(monkeypatch):
    fake = _CountingLatestClient({"version": None})
    monkeypatch.setattr(s3, "client", lambda: fake)

    assert dep_repo.get_latest("ios") is None
    assert dep_repo.get_latest("ios") is None
    assert fake.get_calls == 1

    dep_repo.get_latest("android")
    assert fake.get_calls == 2


def test_generate_presigned_model_download_url_parses_s3_url(monkeypatch):
    captured = {}

    class _FakeClient:
        def generate_presigned_url(self, op, Params, ExpiresIn):
            captured.update(op=op, params=Params, expires=ExpiresIn)
            return "https://signed.example/x"

    monkeypatch.setattr(s3, "client", lambda: _FakeClient())
    url = dep_repo.generate_presigned_model_download_url("s3://fitset-models/ios/v1.3/FitSet.mlpackage.zip")

    assert url == "https://signed.example/x"
    assert captured["op"] == "get_object"
    assert captured["params"] == {"Bucket": "fitset-models", "Key": "ios/v1.3/FitSet.mlpackage.zip"}
    assert captured["expires"] == 3600


def test_next_version_empty_starts_at_v1_0(monkeypatch):
    monkeypatch.setattr(train_repo, "list_model_versions", lambda p: [])
    assert train_repo.next_version("ios") == "v1.0"


def test_next_version_increments_minor(monkeypatch):
    monkeypatch.setattr(train_repo, "list_model_versions", lambda p: ["v1.0", "v1.1", "v1.2"])
    assert train_repo.next_version("ios") == "v1.3"


def test_next_version_uses_latest_sorted(monkeypatch):
    monkeypatch.setattr(train_repo, "list_model_versions", lambda p: ["v1.0", "v1.9"])
    assert train_repo.next_version("android") == "v1.10"


def test_next_version_compares_minor_numerically(monkeypatch):
    monkeypatch.setattr(train_repo, "list_model_versions", lambda p: ["v1.0", "v1.9", "v1.10"])
    assert train_repo.next_version("android") == "v1.11"


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

    monkeypatch.setattr(s3, "client", lambda: _FakeClient())
    assert train_repo.list_model_versions("ios") == ["v1.0", "v1.2"]
