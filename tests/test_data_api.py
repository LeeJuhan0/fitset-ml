"""데이터 수집/조회 라우터 (app.api.data) — S3 의존은 monkeypatch."""

import app.api.data as data_mod


def test_list_data_wraps_index(client, monkeypatch):
    index = {"platform": "ios", "files": [{"filename": "a.csv", "class": "SQUAT"}]}
    monkeypatch.setattr(data_mod, "get_index", lambda p: index)

    resp = client.get("/api/v1/ios/data")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"] == index


def test_presigned_url_success(client, monkeypatch):
    monkeypatch.setattr(
        data_mod, "generate_presigned_upload_url",
        lambda platform, class_name, filename: "https://signed.example/put",
    )
    resp = client.get("/api/v1/ios/data/presigned-url?filename=SQUAT_1.csv&class=SQUAT")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["presignedUrl"] == "https://signed.example/put"
    assert data["expiresIn"] == 300
    assert data["s3Key"] == "ios/raw/SQUAT/SQUAT_1.csv"


def test_presigned_url_rejects_unknown_class(client):
    resp = client.get("/api/v1/ios/data/presigned-url?filename=x.csv&class=PLANK")
    assert resp.status_code == 400


def _fake_update_index(index):
    """update_index 흉내 — mutate 를 주어진 index 에 제자리 적용하고 반환."""
    def _update(platform, mutate):
        mutate(index)
        return index
    return _update


def test_upload_confirm_appends_new_file(client, monkeypatch):
    index = {"platform": "ios", "files": []}
    monkeypatch.setattr(data_mod, "update_index", _fake_update_index(index))

    resp = client.post(
        "/api/v1/ios/data/upload-confirm",
        json={"filename": "SQUAT_1.csv", "class_name": "SQUAT"},
    )
    assert resp.status_code == 200
    assert index["files"][0]["filename"] == "SQUAT_1.csv"
    assert index["files"][0]["trainedInVersion"] is None


def test_upload_confirm_is_idempotent_for_duplicate(client, monkeypatch):
    index = {"platform": "ios", "files": [{"filename": "SQUAT_1.csv", "class": "SQUAT"}]}
    monkeypatch.setattr(data_mod, "update_index", _fake_update_index(index))

    resp = client.post(
        "/api/v1/ios/data/upload-confirm",
        json={"filename": "SQUAT_1.csv", "class_name": "SQUAT"},
    )
    assert resp.status_code == 200
    # 이미 존재 → 중복 추가 없음
    assert len(index["files"]) == 1


def test_upload_confirm_rejects_unknown_class(client):
    resp = client.post(
        "/api/v1/ios/data/upload-confirm",
        json={"filename": "x.csv", "class_name": "PLANK"},
    )
    assert resp.status_code == 400
