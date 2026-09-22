from conftest import async_
import app.exercises.service as ex_mod
from app.core.models import ExerciseRead


def test_list_exercises(admin_client, monkeypatch):
    monkeypatch.setattr(ex_mod, "list_exercises", async_(lambda s: [
        ExerciseRead(id=1, index=0, class_name="SQUAT", slug="bodyweight-squat", name="맨몸 스쿼트", exercise_id="u1", phase_supported=True),
    ]))
    resp = admin_client.get("/api/v1/exercises")
    assert resp.status_code == 200
    e = resp.json()["data"]["exercises"][0]
    assert e["class"] == "SQUAT" and e["slug"] == "bodyweight-squat" and e["phaseSupported"] is True


def test_seed_reads_mapping_and_upserts(admin_client, monkeypatch):
    monkeypatch.setattr(ex_mod, "load_mapping", lambda src: {"modelClassCount": 14, "classes": [{"index": 0, "class": "SQUAT", "slug": "s", "name": "n"}]})
    monkeypatch.setattr(ex_mod, "upsert_exercises", async_(lambda s, items: {"added": len(items), "updated": 0}))
    resp = admin_client.post("/api/v1/exercises/seed?source=s3://b/k")
    assert resp.status_code == 200
    assert resp.json()["data"] == {"source": "s3://b/k", "modelClassCount": 14, "added": 1, "updated": 0}


def test_exercises_require_basic(client):
    assert client.get("/api/v1/exercises").status_code == 401
