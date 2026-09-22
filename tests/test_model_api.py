import pytest

import app.deployment.service as model_mod


@pytest.fixture(autouse=True)
def reset_reports():
    model_mod._reports.clear()
    yield
    model_mod._reports.clear()


@pytest.fixture(autouse=True)
def stub_presign(monkeypatch):
    monkeypatch.setattr(
        model_mod, "generate_presigned_model_download_url",
        lambda url: f"https://signed.example/{url.removeprefix('s3://')}",
    )


def test_model_latest_404_when_not_deployed(admin_client, monkeypatch):
    monkeypatch.setattr(model_mod, "get_latest", lambda p: None)
    resp = admin_client.get("/api/v1/ios/model/latest")
    assert resp.status_code == 404


def test_model_latest_up_to_date_flag(admin_client, monkeypatch):
    monkeypatch.setattr(
        model_mod, "get_latest",
        lambda p: {"version": "v1.3", "modelUrl": "s3://m/ios/v1.3/FitSet.mlpackage"},
    )

    same = model_mod.latest("ios", "v1.3")
    assert same.latest_version == "v1.3"
    assert same.is_up_to_date is True
    assert same.model_url == "https://signed.example/m/ios/v1.3/FitSet.mlpackage"
    assert same.meta_url == "https://d31w3ih1t93w7x.cloudfront.net/models/class-mapping.json"

    older = model_mod.latest("ios", "v1.0")
    assert older.is_up_to_date is False


def test_model_latest_records_version_report(admin_client, monkeypatch):
    monkeypatch.setattr(
        model_mod, "get_latest",
        lambda p: {"version": "v1.3", "modelUrl": "s3://m"},
    )
    model_mod.latest("ios", "v1.3")
    model_mod.latest("ios", "v1.3")
    model_mod.latest("ios", "v1.2")

    stats = admin_client.get("/api/v1/ios/model/version-stats").json()["data"]
    assert stats["latestVersion"] == "v1.3"
    assert stats["totalReports"] == 3
    counts = {s["version"]: s["count"] for s in stats["stats"]}
    assert counts == {"v1.3": 2, "v1.2": 1}
    assert stats["stats"][0]["version"] == "v1.3"
    assert abs(sum(s["ratio"] for s in stats["stats"]) - 1.0) < 0.01


def test_old_reports_expire_from_window(admin_client, monkeypatch):
    monkeypatch.setattr(model_mod, "get_latest", lambda p: {"version": "v1.3", "modelUrl": "s3://m"})
    model_mod._reports["ios"].append((0.0, "v1.2"))
    model_mod.latest("ios", "v1.3")

    stats = admin_client.get("/api/v1/ios/model/version-stats").json()["data"]
    counts = {s["version"]: s["count"] for s in stats["stats"]}
    assert counts == {"v1.3": 1}
    assert stats["totalReports"] == 1


def test_report_ignored_without_current_version(admin_client, monkeypatch):
    monkeypatch.setattr(model_mod, "get_latest", lambda p: {"version": "v1.3", "modelUrl": "s3://m"})
    resp = admin_client.get("/api/v1/ios/model/latest")
    assert resp.status_code == 200

    stats = admin_client.get("/api/v1/ios/model/version-stats").json()["data"]
    assert stats["stats"] == []
    assert stats["totalReports"] == 0


def test_version_stats_isolated_per_platform(admin_client, monkeypatch):
    monkeypatch.setattr(model_mod, "get_latest", lambda p: {"version": "v1.0", "modelUrl": "s3://m"})
    model_mod.latest("ios", "v1.0")

    android = admin_client.get("/api/v1/android/model/version-stats").json()["data"]
    assert android["stats"] == []


def test_admin_latest_alias_does_not_pollute_stats(admin_client, monkeypatch):
    monkeypatch.setattr(model_mod, "get_latest", lambda p: {"version": "v1.3", "modelUrl": "s3://m"})
    resp = admin_client.get("/api/v1/ios/model/latest")
    assert resp.status_code == 200
    assert resp.json()["data"]["latestVersion"] == "v1.3"

    stats = admin_client.get("/api/v1/ios/model/version-stats").json()["data"]
    assert stats["totalReports"] == 0
