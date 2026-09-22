from conftest import async_
import app.data.service as data_mod
from app.data.models import DatasetFileRead


def _entry(filename="a.csv", class_name="SQUAT", uploaded=True):
    return DatasetFileRead(
        id=1, filename=filename, class_name=class_name, device_id="watch01",
        bucket="fitset-dataset", s3_key=f"ios/raw/{class_name}/{filename}",
        uploaded=uploaded, created_at="2026-07-22T00:00:00+00:00",
    )


def test_list_data_wraps_rows(admin_client, monkeypatch):
    monkeypatch.setattr(data_mod, "list_files", async_(lambda s, p: [_entry()]))

    resp = admin_client.get("/api/v1/ios/data")
    assert resp.status_code == 200
    body = resp.json()
    assert body["traceId"]
    assert body["data"]["platform"] == "ios"
    f = body["data"]["files"][0]
    assert f["filename"] == "a.csv"
    assert f["class"] == "SQUAT"
    assert f["deviceId"] == "watch01"
    assert f["trainedInVersion"] is None
    assert f["isTrained"] is False and f["format"] == "csv"
    assert f["s3Key"] == "ios/raw/SQUAT/a.csv"


def _stats_csv(rows_sec: int = 10, hz: int = 100) -> bytes:
    """hz 샘플/초 × rows_sec 초짜리 CSV. 앞 3초는 ax=99(노이즈), 이후는 ax=1"""
    lines = ["timestamp,ax,ay,az,gx,gy,gz,label"]
    for i in range(rows_sec * hz):
        t_ns = i * (1_000_000_000 // hz)
        ax = 99.0 if i < 3 * hz else 1.0
        lines.append(f"{t_ns},{ax},0.5,-9.8,0.1,-0.1,0.0,SQUAT")
    return "\n".join(lines).encode()


def test_data_stats_trims_edges(admin_client, monkeypatch):
    monkeypatch.setattr(data_mod, "list_files", async_(lambda s, p: [_entry("SQUAT_ABC_0001.csv")]))
    monkeypatch.setattr(
        data_mod, "download_csv_bytes",
        lambda bucket, key: _stats_csv(),
    )

    resp = admin_client.get("/api/v1/ios/data/stats?filename=SQUAT_ABC_0001.csv")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["class"] == "SQUAT"
    assert data["trimApplied"] is True
    assert data["totalRows"] == 1000
    assert data["usedRows"] < 1000
    ax = next(c for c in data["channels"] if c["channel"] == "ax")
    assert ax["mean"] == 1.0
    assert ax["max"] == 1.0
    assert {c["channel"] for c in data["channels"]} == {"ax", "ay", "az", "gx", "gy", "gz"}


def test_data_stats_short_file_skips_trim(admin_client, monkeypatch):
    monkeypatch.setattr(data_mod, "list_files", async_(lambda s, p: [_entry("SQUAT_ABC_0002.csv")]))
    monkeypatch.setattr(
        data_mod, "download_csv_bytes",
        lambda bucket, key: _stats_csv(rows_sec=5),
    )

    resp = admin_client.get("/api/v1/ios/data/stats?filename=SQUAT_ABC_0002.csv")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["trimApplied"] is False
    assert data["usedRows"] == data["totalRows"] == 500


def test_data_stats_404_unknown_file(admin_client, monkeypatch):
    monkeypatch.setattr(data_mod, "list_files", async_(lambda s, p: []))
    resp = admin_client.get("/api/v1/ios/data/stats?filename=NOPE.csv")
    assert resp.status_code == 404


def test_admin_presigned_url_targets_dataset_bucket(admin_client, monkeypatch):
    monkeypatch.setattr(
        data_mod, "reserve_admin_upload",
        async_(lambda s, platform, class_name, device_id: (f"{class_name}_{device_id}_0001.csv", f"{platform}/raw/000_{class_name}/{class_name}_{device_id}_0001.csv"),)
    )
    monkeypatch.setattr(
        data_mod, "generate_presigned_admin_upload_url",
        lambda key: "https://signed.example/admin-put",
    )
    resp = admin_client.get("/api/v1/ios/data/presigned-url?class=SQUAT&deviceId=DEV01")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["presignedUrl"] == "https://signed.example/admin-put"
    assert data["filename"] == "SQUAT_DEV01_0001.csv"
    assert data["s3Key"] == "ios/raw/000_SQUAT/SQUAT_DEV01_0001.csv"


def test_admin_presigned_url_rejects_unknown_class(admin_client):
    resp = admin_client.get("/api/v1/ios/data/presigned-url?class=PLANK&deviceId=DEV01")
    assert resp.status_code == 400


def _fake_admin_mark(index):
    def _mark(s, platform, filename):
        for f in index["files"]:
            if f["filename"] == filename:
                f["uploaded"] = True
                return True
        return False
    return _mark


def test_admin_upload_confirm_marks_index(admin_client, monkeypatch):
    index = {"platform": "ios", "files": [
        {"filename": "SQUAT_DEV01_0001.csv", "class": "SQUAT", "uploaded": False},
    ]}
    monkeypatch.setattr(data_mod, "mark_admin_uploaded", async_(_fake_admin_mark(index)))
    resp = admin_client.post(
        "/api/v1/ios/data/upload-confirm",
        json={"filename": "SQUAT_DEV01_0001.csv", "class_name": "SQUAT"},
    )
    assert resp.status_code == 200
    assert index["files"][0]["uploaded"] is True


def test_admin_upload_confirm_404_when_not_reserved(admin_client, monkeypatch):
    index = {"platform": "ios", "files": []}
    monkeypatch.setattr(data_mod, "mark_admin_uploaded", async_(_fake_admin_mark(index)))
    resp = admin_client.post(
        "/api/v1/ios/data/upload-confirm",
        json={"filename": "SQUAT_DEV01_9999.csv", "class_name": "SQUAT"},
    )
    assert resp.status_code == 404


def test_admin_upload_requires_basic():
    from fastapi.testclient import TestClient
    from app.main import app
    bare = TestClient(app)
    resp = bare.get("/api/v1/ios/data/presigned-url?class=SQUAT&deviceId=DEV01")
    assert resp.status_code == 401
