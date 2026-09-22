import pytest

from conftest import async_

ENDPOINTS = [
    ("admin_client", "get", "/api/v1/{p}/model/latest"),
    ("admin_client", "get", "/api/v1/{p}/data"),
    ("admin_client", "get", "/api/v1/{p}/train/status?jobId=x"),
    ("admin_client", "get", "/api/v1/{p}/model/version-stats"),
    ("admin_client", "get", "/api/v1/{p}/runs"),
]


@pytest.mark.parametrize("fixture,method,path", ENDPOINTS)
@pytest.mark.parametrize("bad", ["web", "iOS", "android2", "watchos", ""])
def test_invalid_platform_returns_400(request, fixture, method, path, bad):
    http = request.getfixturevalue(fixture)
    url = path.format(p=bad)
    resp = getattr(http, method)(url)
    if bad == "":
        assert resp.status_code in (400, 404)
    else:
        assert resp.status_code == 400


@pytest.mark.parametrize("good", ["ios", "android"])
def test_valid_platform_passes_validation(admin_client, monkeypatch, good):
    import app.data.service as data_mod
    monkeypatch.setattr(data_mod, "list_files", async_(lambda s, p: []))

    resp = admin_client.get(f"/api/v1/{good}/data")
    assert resp.status_code == 200
    assert resp.json()["data"]["platform"] == good
