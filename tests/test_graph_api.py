import pytest
from conftest import async_
import app.graph.service as graph_mod
from app.data.models import DatasetFileRead


def _entry(filename="SQUAT_ABC_0001.csv"):
    return DatasetFileRead(
        id=1, filename=filename, class_name="SQUAT", device_id="watch01",
        bucket="fitset-dataset", s3_key=f"ios/raw/SQUAT/{filename}",
        uploaded=True, created_at="2026-07-22T00:00:00+00:00",
    )


def _ns_csv(rows_sec: int = 10, hz: int = 100) -> bytes:
    """timestamp 가 ns 단위인 CSV"""
    lines = ["timestamp,ax,ay,az,gx,gy,gz,label"]
    for i in range(rows_sec * hz):
        lines.append(f"{i * (1_000_000_000 // hz)},{i % 7},0.5,-9.8,0.1,-0.1,0.0,SQUAT")
    return "\n".join(lines).encode()


def _seconds_csv(rows_sec: int = 10, hz: int = 100) -> bytes:
    """iOS 수집앱처럼 timestamp 가 초 단위인 CSV"""
    lines = ["timestamp,ax,ay,az,gx,gy,gz,label"]
    for i in range(rows_sec * hz):
        lines.append(f"{1782545010 + i / hz:.3f},{i % 7},0.5,-1.0,0.1,-0.1,0.0,SQUAT")
    return "\n".join(lines).encode()


@pytest.mark.parametrize("csv_bytes", [_ns_csv(), _seconds_csv()], ids=["ns", "sec"])
def test_data_imu_seconds_from_start(admin_client, monkeypatch, csv_bytes):
    monkeypatch.setattr(graph_mod, "list_files", async_(lambda s, p: [_entry("SQUAT_ABC_0001.csv")]))
    monkeypatch.setattr(graph_mod, "download_csv_bytes", lambda bucket, key: csv_bytes)

    data = admin_client.get("/api/v1/ios/graph/imu?filename=SQUAT_ABC_0001.csv").json()["data"]
    assert data["t"][0] == 0
    assert 9.9 <= data["t"][-1] <= 10.0
    assert set(data["channels"]) == {"ax", "ay", "az", "gx", "gy", "gz"}
    assert len(data["channels"]["ax"]) == len(data["t"]) == 1000


def test_data_imu_thins_long_file(admin_client, monkeypatch):
    monkeypatch.setattr(graph_mod, "list_files", async_(lambda s, p: [_entry("SQUAT_ABC_0001.csv")]))
    monkeypatch.setattr(graph_mod, "download_csv_bytes", lambda bucket, key: _seconds_csv(rows_sec=600))

    data = admin_client.get("/api/v1/ios/graph/imu?filename=SQUAT_ABC_0001.csv").json()["data"]
    assert len(data["t"]) <= graph_mod.IMU_MAX_POINTS
    assert data["t"][-1] > 599


def test_data_imu_404_unknown_file(admin_client, monkeypatch):
    monkeypatch.setattr(graph_mod, "list_files", async_(lambda s, p: []))
    assert admin_client.get("/api/v1/ios/graph/imu?filename=NOPE.csv").status_code == 404
