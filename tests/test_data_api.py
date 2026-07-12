"""데이터 수집/조회 API (app.data) — S3 의존은 service 네임스페이스에서 monkeypatch."""

import app.data.service as data_mod


def test_list_data_wraps_index(client, monkeypatch):
    index = {"platform": "ios", "files": [{"filename": "a.csv", "class": "SQUAT"}]}
    monkeypatch.setattr(data_mod, "get_index", lambda p: index)

    resp = client.get("/api/v1/ios/data")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"] == index


def test_presigned_url_server_assigns_filename(client, monkeypatch):
    # 서버가 인덱스 보고 이름을 정한다 → reserve_upload를 가짜로
    monkeypatch.setattr(
        data_mod, "reserve_upload",
        lambda platform, class_name, device_id: f"{class_name}_{device_id}_0001.csv",
    )
    monkeypatch.setattr(
        data_mod, "generate_presigned_upload_url",
        lambda platform, class_name, filename: "https://signed.example/put",
    )
    resp = client.get("/api/v1/ios/data/presigned-url?class=SQUAT&deviceId=ABC12345")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["presignedUrl"] == "https://signed.example/put"
    assert data["expiresIn"] == 300
    assert data["filename"] == "SQUAT_ABC12345_0001.csv"
    assert data["s3Key"] == "ios/raw/SQUAT/SQUAT_ABC12345_0001.csv"


def test_presigned_url_rejects_unknown_class(client):
    resp = client.get("/api/v1/ios/data/presigned-url?class=PLANK&deviceId=ABC12345")
    assert resp.status_code == 400


def test_presigned_url_rejects_bad_device_id(client):
    # deviceId가 S3 키에 들어가므로 경로 조작 시도는 400 (reserve 전에 차단)
    resp = client.get("/api/v1/ios/data/presigned-url?class=SQUAT&deviceId=../evil")
    assert resp.status_code == 400


def test_presigned_url_requires_device_id(client):
    resp = client.get("/api/v1/ios/data/presigned-url?class=SQUAT")
    assert resp.status_code == 422  # 필수 쿼리 누락


def _fake_mark_uploaded(index):
    def _mark(platform, filename):
        for f in index["files"]:
            if f["filename"] == filename:
                f["uploaded"] = True
                return True
        return False
    return _mark


def test_upload_confirm_marks_uploaded(client, monkeypatch):
    index = {"platform": "ios", "files": [
        {"filename": "SQUAT_ABC_0001.csv", "class": "SQUAT", "uploaded": False},
    ]}
    monkeypatch.setattr(data_mod, "mark_uploaded", _fake_mark_uploaded(index))

    resp = client.post(
        "/api/v1/ios/data/upload-confirm",
        json={"filename": "SQUAT_ABC_0001.csv", "class_name": "SQUAT"},
    )
    assert resp.status_code == 200
    assert index["files"][0]["uploaded"] is True


def test_upload_confirm_404_when_not_reserved(client, monkeypatch):
    index = {"platform": "ios", "files": []}  # 예약된 항목 없음
    monkeypatch.setattr(data_mod, "mark_uploaded", _fake_mark_uploaded(index))
    resp = client.post(
        "/api/v1/ios/data/upload-confirm",
        json={"filename": "SQUAT_ABC_9999.csv", "class_name": "SQUAT"},
    )
    assert resp.status_code == 404


def test_upload_confirm_rejects_unknown_class(client):
    resp = client.post(
        "/api/v1/ios/data/upload-confirm",
        json={"filename": "x.csv", "class_name": "PLANK"},
    )
    assert resp.status_code == 400
