"""데이터 수집/조회 API (app.data) — S3 의존은 service 네임스페이스에서 monkeypatch."""

import app.data.service as data_mod


def test_list_data_wraps_index(admin_client, monkeypatch):
    # reserve_upload가 기록하는 실제 항목 형태 그대로 (response_model 검증 대상)
    index = {
        "platform": "ios",
        "files": [{
            "filename": "a.csv",
            "class": "SQUAT",
            "deviceId": "watch01",
            "collectedAt": "2026-07-22T00:00:00+00:00",
            "uploaded": True,
            "trainedInVersion": None,
        }],
    }
    monkeypatch.setattr(data_mod, "get_index", lambda p: index)

    resp = admin_client.get("/api/v1/ios/data")
    assert resp.status_code == 200
    body = resp.json()
    assert body["traceId"]
    assert body["data"] == index


def test_presigned_url_server_assigns_filename(user_client, monkeypatch):
    # 서버가 업로드 대장 보고 이름을 정한다(주인=토큰 userId) → reserve_user_upload를 가짜로
    monkeypatch.setattr(
        data_mod, "reserve_user_upload",
        lambda platform, class_name, user_id, device_id: f"{class_name}_{user_id}_0001.csv",
    )
    monkeypatch.setattr(
        data_mod, "generate_presigned_user_upload_url",
        lambda platform, user_id, filename: "https://signed.example/put",
    )
    resp = user_client.get("/ml/v1/ios/data/presigned-url?class=SQUAT&deviceId=ABC12345")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["presignedUrl"] == "https://signed.example/put"
    assert data["expiresIn"] == 300
    # 채번 주인은 deviceId가 아니라 토큰의 userId(user-1), 키는 격리 버킷의 {platform}/{userId}/
    assert data["filename"] == "SQUAT_user-1_0001.csv"
    assert data["s3Key"] == "ios/user-1/SQUAT_user-1_0001.csv"


def test_presigned_url_rejects_unknown_class(user_client):
    resp = user_client.get("/ml/v1/ios/data/presigned-url?class=PLANK&deviceId=ABC12345")
    assert resp.status_code == 400


def test_presigned_url_rejects_bad_device_id(user_client):
    # deviceId가 S3 키에 들어가므로 경로 조작 시도는 400 (reserve 전에 차단)
    resp = user_client.get("/ml/v1/ios/data/presigned-url?class=SQUAT&deviceId=../evil")
    assert resp.status_code == 400


def test_presigned_url_requires_device_id(user_client):
    resp = user_client.get("/ml/v1/ios/data/presigned-url?class=SQUAT")
    assert resp.status_code == 400  # 필수 쿼리 누락 — 검증 실패는 400 INVALID_REQUEST (팀 규약)


def _fake_mark_uploaded(index):
    def _mark(platform, filename):
        for f in index["uploads"]:
            if f["filename"] == filename:
                f["uploaded"] = True
                return True
        return False
    return _mark


def test_upload_confirm_marks_uploaded(user_client, monkeypatch):
    index = {"platform": "ios", "uploads": [
        {"filename": "SQUAT_ABC_0001.csv", "class": "SQUAT", "uploaded": False},
    ]}
    monkeypatch.setattr(data_mod, "mark_user_uploaded", _fake_mark_uploaded(index))

    resp = user_client.post(
        "/ml/v1/ios/data/upload-confirm",
        json={"filename": "SQUAT_ABC_0001.csv", "class_name": "SQUAT"},
    )
    assert resp.status_code == 200
    assert index["uploads"][0]["uploaded"] is True


def test_upload_confirm_404_when_not_reserved(user_client, monkeypatch):
    index = {"platform": "ios", "uploads": []}  # 예약된 항목 없음
    monkeypatch.setattr(data_mod, "mark_user_uploaded", _fake_mark_uploaded(index))
    resp = user_client.post(
        "/ml/v1/ios/data/upload-confirm",
        json={"filename": "SQUAT_ABC_9999.csv", "class_name": "SQUAT"},
    )
    assert resp.status_code == 404


def test_upload_confirm_rejects_unknown_class(user_client):
    resp = user_client.post(
        "/ml/v1/ios/data/upload-confirm",
        json={"filename": "x.csv", "class_name": "PLANK"},
    )
    assert resp.status_code == 400


# ── GET /data/stats ──────────────────────────────────────────────────────────

def _stats_csv(rows_sec: int = 10, hz: int = 100) -> bytes:
    """hz 샘플/초 × rows_sec 초짜리 CSV. 앞 3초는 ax=99(노이즈), 이후는 ax=1."""
    lines = ["timestamp,ax,ay,az,gx,gy,gz,label"]
    for i in range(rows_sec * hz):
        t_ns = i * (1_000_000_000 // hz)
        ax = 99.0 if i < 3 * hz else 1.0
        lines.append(f"{t_ns},{ax},0.5,-9.8,0.1,-0.1,0.0,SQUAT")
    return "\n".join(lines).encode()


def test_data_stats_trims_edges(admin_client, monkeypatch):
    index = {"platform": "ios", "files": [
        {"filename": "SQUAT_ABC_0001.csv", "class": "SQUAT", "uploaded": True},
    ]}
    monkeypatch.setattr(data_mod, "get_index", lambda p: index)
    monkeypatch.setattr(
        data_mod, "download_csv_bytes",
        lambda platform, class_name, filename: _stats_csv(),
    )

    resp = admin_client.get("/api/v1/ios/data/stats?filename=SQUAT_ABC_0001.csv")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["class"] == "SQUAT"
    assert data["trimApplied"] is True
    assert data["totalRows"] == 1000
    assert data["usedRows"] < 1000
    ax = next(c for c in data["channels"] if c["channel"] == "ax")
    # 앞 3초의 ax=99 노이즈가 트림으로 빠졌으면 평균은 정확히 1
    assert ax["mean"] == 1.0
    assert ax["max"] == 1.0
    assert {c["channel"] for c in data["channels"]} == {"ax", "ay", "az", "gx", "gy", "gz"}


def test_data_stats_short_file_skips_trim(admin_client, monkeypatch):
    # 총 5초 → 앞뒤 3초 트림하면 빈 구간 → 전체로 계산하고 trimApplied=False
    index = {"platform": "ios", "files": [
        {"filename": "SQUAT_ABC_0002.csv", "class": "SQUAT", "uploaded": True},
    ]}
    monkeypatch.setattr(data_mod, "get_index", lambda p: index)
    monkeypatch.setattr(
        data_mod, "download_csv_bytes",
        lambda platform, class_name, filename: _stats_csv(rows_sec=5),
    )

    resp = admin_client.get("/api/v1/ios/data/stats?filename=SQUAT_ABC_0002.csv")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["trimApplied"] is False
    assert data["usedRows"] == data["totalRows"] == 500


def test_data_stats_404_unknown_file(admin_client, monkeypatch):
    monkeypatch.setattr(data_mod, "get_index", lambda p: {"platform": "ios", "files": []})
    resp = admin_client.get("/api/v1/ios/data/stats?filename=NOPE.csv")
    assert resp.status_code == 404


# ── 어드민 직행 업로드 — dataset 버킷(신뢰 영역) + 학습 인덱스 직등록 ────────

def test_admin_presigned_url_targets_dataset_bucket(admin_client, monkeypatch):
    # 채번 주인은 deviceId(구 수집앱 규칙), 키는 dataset 버킷의 raw 경로
    monkeypatch.setattr(
        data_mod, "reserve_admin_upload",
        lambda platform, class_name, device_id: f"{class_name}_{device_id}_0001.csv",
    )
    monkeypatch.setattr(
        data_mod, "generate_presigned_admin_upload_url",
        lambda platform, class_name, filename: "https://signed.example/admin-put",
    )
    resp = admin_client.get("/api/v1/ios/data/presigned-url?class=SQUAT&deviceId=DEV01")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["presignedUrl"] == "https://signed.example/admin-put"
    assert data["filename"] == "SQUAT_DEV01_0001.csv"
    assert data["s3Key"] == "ios/raw/SQUAT/SQUAT_DEV01_0001.csv"


def test_admin_presigned_url_rejects_unknown_class(admin_client):
    resp = admin_client.get("/api/v1/ios/data/presigned-url?class=PLANK&deviceId=DEV01")
    assert resp.status_code == 400


def _fake_admin_mark(index):
    def _mark(platform, filename):
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
    monkeypatch.setattr(data_mod, "mark_admin_uploaded", _fake_admin_mark(index))
    resp = admin_client.post(
        "/api/v1/ios/data/upload-confirm",
        json={"filename": "SQUAT_DEV01_0001.csv", "class_name": "SQUAT"},
    )
    assert resp.status_code == 200
    assert index["files"][0]["uploaded"] is True


def test_admin_upload_confirm_404_when_not_reserved(admin_client, monkeypatch):
    index = {"platform": "ios", "files": []}
    monkeypatch.setattr(data_mod, "mark_admin_uploaded", _fake_admin_mark(index))
    resp = admin_client.post(
        "/api/v1/ios/data/upload-confirm",
        json={"filename": "SQUAT_DEV01_9999.csv", "class_name": "SQUAT"},
    )
    assert resp.status_code == 404


def test_admin_upload_requires_basic():
    from fastapi.testclient import TestClient
    from admin_api.main import app
    bare = TestClient(app)
    resp = bare.get("/api/v1/ios/data/presigned-url?class=SQUAT&deviceId=DEV01")
    assert resp.status_code == 401
