"""앱용 모델 조회 + 버전 분포 (app.deployment).

version-stats 는 인메모리 시간 윈도우 집계라 테스트마다 상태를 초기화한다.
패치 대상은 유스케이스가 사는 service 네임스페이스."""

import pytest

import app.deployment.service as model_mod


@pytest.fixture(autouse=True)
def reset_reports():
    model_mod._reports.clear()
    yield
    model_mod._reports.clear()


@pytest.fixture(autouse=True)
def stub_presign(monkeypatch):
    # 실제 AWS 서명 없이 presigned URL 변환만 흉내낸다.
    monkeypatch.setattr(
        model_mod, "generate_presigned_model_download_url",
        lambda url: f"https://signed.example/{url.removeprefix('s3://')}",
    )


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
    # 앱에는 s3:// 정본이 아니라 다운로드 가능한 서명 URL이 내려간다
    assert same["modelUrl"] == "https://signed.example/m/ios/v1.3/FitSet.mlpackage"
    # 클래스 번호와 운동 slug 매핑 테이블은 공개 CDN URL로 내려간다
    assert same["metaUrl"] == "https://dtcevtkuvdwt9.cloudfront.net/models/class-mapping.json"

    older = client.get("/api/v1/ios/model/latest?currentVersion=v1.0").json()["data"]
    assert older["isUpToDate"] is False


def test_model_latest_records_version_report(client, monkeypatch):
    monkeypatch.setattr(
        model_mod, "get_latest",
        lambda p: {"version": "v1.3", "modelUrl": "s3://m"},
    )
    # 앱 폴링 시뮬레이션: v1.3 두 번, v1.2 한 번 (윈도우 안이므로 전부 집계)
    client.get("/api/v1/ios/model/latest?currentVersion=v1.3")
    client.get("/api/v1/ios/model/latest?currentVersion=v1.3")
    client.get("/api/v1/ios/model/latest?currentVersion=v1.2")

    stats = client.get("/api/v1/ios/model/version-stats").json()["data"]
    assert stats["latestVersion"] == "v1.3"
    assert stats["totalReports"] == 3
    counts = {s["version"]: s["count"] for s in stats["stats"]}
    assert counts == {"v1.3": 2, "v1.2": 1}
    # 정렬: count 내림차순
    assert stats["stats"][0]["version"] == "v1.3"
    # ratio 합 ≈ 1.0
    assert abs(sum(s["ratio"] for s in stats["stats"]) - 1.0) < 0.01


def test_old_reports_expire_from_window(client, monkeypatch):
    monkeypatch.setattr(model_mod, "get_latest", lambda p: {"version": "v1.3", "modelUrl": "s3://m"})
    # 교체 전(v1.2) 리포트가 윈도우(24h)보다 오래됨 — 조회 시 만료되어 빠져야 한다
    model_mod._reports["ios"].append((0.0, "v1.2"))
    client.get("/api/v1/ios/model/latest?currentVersion=v1.3")

    stats = client.get("/api/v1/ios/model/version-stats").json()["data"]
    counts = {s["version"]: s["count"] for s in stats["stats"]}
    assert counts == {"v1.3": 1}
    assert stats["totalReports"] == 1


def test_report_ignored_without_current_version(client, monkeypatch):
    monkeypatch.setattr(model_mod, "get_latest", lambda p: {"version": "v1.3", "modelUrl": "s3://m"})
    # currentVersion 없이 폴링하면 모델 조회는 정상, 분포 집계에는 반영 안 됨
    resp = client.get("/api/v1/ios/model/latest")
    assert resp.status_code == 200

    stats = client.get("/api/v1/ios/model/version-stats").json()["data"]
    assert stats["stats"] == []
    assert stats["totalReports"] == 0


def test_version_stats_isolated_per_platform(client, monkeypatch):
    monkeypatch.setattr(model_mod, "get_latest", lambda p: {"version": "v1.0", "modelUrl": "s3://m"})
    client.get("/api/v1/ios/model/latest?currentVersion=v1.0")

    # android 는 별도 집계 → 비어 있어야 함
    android = client.get("/api/v1/android/model/version-stats").json()["data"]
    assert android["stats"] == []
