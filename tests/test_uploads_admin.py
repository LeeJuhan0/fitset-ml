# ─────────────────────────────────────────────────────────────────────────────
# 유저 업로드 대장·승격 API (어드민) — 목록은 상태 필터, 승인·반려는 스켈레톤(501).
# S3 의존은 service 네임스페이스에서 monkeypatch.
# ─────────────────────────────────────────────────────────────────────────────
import pytest

import app.data.service as data_mod

UPLOADS = [
    {"filename": "SQUAT_user1_0001.csv", "class": "SQUAT", "userId": "user1",
     "deviceId": "DEV1", "collectedAt": "2026-08-24T00:00:00+00:00",
     "uploaded": True, "status": "pending"},
    {"filename": "PUSHUP_user2_0001.csv", "class": "PUSHUP", "userId": "user2",
     "deviceId": "DEV2", "collectedAt": "2026-08-24T01:00:00+00:00",
     "uploaded": True, "status": "approved"},
]


@pytest.fixture
def uploads_index(monkeypatch):
    index = {"platform": "ios", "uploads": [dict(u) for u in UPLOADS]}
    monkeypatch.setattr(data_mod, "get_uploads_index", lambda p: index)
    return index


def test_list_uploads_returns_all_without_filter(admin_client, uploads_index):
    resp = admin_client.get("/api/admin/v1/ios/uploads")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["platform"] == "ios"
    assert [u["filename"] for u in data["uploads"]] == [
        "SQUAT_user1_0001.csv", "PUSHUP_user2_0001.csv",
    ]
    # 대장 항목 필드가 응답 스키마로 그대로 나간다 (userId·status 포함)
    first = data["uploads"][0]
    assert first["userId"] == "user1"
    assert first["status"] == "pending"


def test_list_uploads_filters_by_status(admin_client, uploads_index):
    resp = admin_client.get("/api/admin/v1/ios/uploads?status=pending")
    assert resp.status_code == 200
    uploads = resp.json()["data"]["uploads"]
    assert [u["filename"] for u in uploads] == ["SQUAT_user1_0001.csv"]


def test_list_uploads_rejects_unknown_status(admin_client, uploads_index):
    resp = admin_client.get("/api/admin/v1/ios/uploads?status=maybe")
    assert resp.status_code == 400


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_promotion_endpoints_are_skeleton_501(admin_client, action):
    # 인터페이스는 확정, 처리 로직은 미구현 — 내부오류(500)가 아니라 501 계약으로 응답
    resp = admin_client.post(f"/api/admin/v1/ios/uploads/SQUAT_user1_0001.csv/{action}")
    assert resp.status_code == 501
    assert resp.json()["error"]["code"] == "NOT_IMPLEMENTED"


def test_uploads_require_admin_auth(client):
    resp = client.get("/api/admin/v1/ios/uploads")
    assert resp.status_code == 401
