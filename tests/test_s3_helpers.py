import app.core.s3 as s3
import app.training.repository as train_repo


def test_key_builders():
    assert s3.csv_key("android", "SQUAT", "a.csv") == "android/raw/SQUAT/a.csv"
    assert s3.model_key("ios", "v1.3", "FitSet.mlpackage") == "ios/v1.3/FitSet.mlpackage"
    assert s3.collect_key("ios", "001_PUSHUP", "PUSHUP_DEV_0001.mov") == "ios/001_PUSHUP/PUSHUP_DEV_0001.mov"


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
