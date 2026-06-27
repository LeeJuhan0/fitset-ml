"""앱용 모델 조회 + 버전 분포 (app.api.model).

version-stats 는 인메모리 집계라 테스트마다 상태를 초기화한다."""

import pytest

import app.api.model as model_mod


@pytest.fixture(autouse=True)
def reset_version_stats():
    model_mod._version_stats.clear()
    yield
    model_mod._version_stats.clear()


def test_model_latest_404_when_not_deployed(client, monkeypatch):
    monkeypatch.setattr(model_mod, "get_latest", lambda p: None)
    resp = client.get("/api/v1/ios/model/latest")
    assert resp.status_code == 404


def test_model_latest_up_to_date_flag(client, monkeypatch):
    monkeypatch.setattr(
        model_mod, "get_latest",
        lambda p: {"version": "v1.3", "modelUrl": "s3://m/ios/v1.3/FitSet.mlpackage"},
    )

    same = client.get("/api/v1/ios/model/latest?currentVersion=v1.3").json()["data"]
    assert same["latestVersion"] == "v1.3"
    assert same["isUpToDate"] is True

    older = client.get("/api/v1/ios/model/latest?currentVersion=v1.0").json()["data"]
    assert older["isUpToDate"] is False


def test_model_latest_records_version_report(client, monkeypatch):
    monkeypatch.setattr(
        model_mod, "get_latest",
        lambda p: {"version": "v1.3", "modelUrl": "s3://m"},
    )
    # 앱 폴링 시뮬레이션: v1.3 두 번, v1.2 한 번
    client.get("/api/v1/ios/model/latest?currentVersion=v1.3")
    client.get("/api/v1/ios/model/latest?currentVersion=v1.3")
    client.get("/api/v1/ios/model/latest?currentVersion=v1.2")

    stats = client.get("/api/v1/ios/model/version-stats").json()["data"]
    assert stats["latestVersion"] == "v1.3"
    counts = {s["version"]: s["count"] for s in stats["stats"]}
    assert counts == {"v1.3": 2, "v1.2": 1}
    # 정렬: count 내림차순
    assert stats["stats"][0]["version"] == "v1.3"
    # ratio 합 ≈ 1.0
    assert abs(sum(s["ratio"] for s in stats["stats"]) - 1.0) < 0.01


def test_version_stats_isolated_per_platform(client, monkeypatch):
    monkeypatch.setattr(model_mod, "get_latest", lambda p: {"version": "v1.0", "modelUrl": "s3://m"})
    client.get("/api/v1/ios/model/latest?currentVersion=v1.0")

    # android 는 별도 집계 → 비어 있어야 함
    android = client.get("/api/v1/android/model/version-stats").json()["data"]
    assert android["stats"] == []
