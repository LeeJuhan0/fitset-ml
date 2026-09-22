from types import SimpleNamespace

from conftest import async_
import app.phase.service as phase_mod
from app.data.models import DatasetFileRead
from app.phase.models import CollectFileRead, PhaseLabelRead, PhaseModelRead


def _entry(filename="PUSHUP_DEV1_0001.csv", class_name="PUSHUP", status="pending", uploaded=True,
           video_start=1789790030.2, label=None):
    return CollectFileRead(
        filename=filename, class_name=class_name, device_id="DEV1",
        csv_bucket="fitset-collect-imu", csv_key=f"ios/{class_name}/{filename}",
        video_bucket="fitset-collect-video", video_key=f"ios/{class_name}/{filename[:-4]}.mov",
        uploaded=uploaded, video_start=video_start, rows=100, status=status,
        created_at="2026-09-22T00:00:00+00:00", label=label,
    )


def test_presigned_url_issues_csv_and_video(admin_client, monkeypatch):
    monkeypatch.setattr(phase_mod, "reserve_collect", async_(lambda s, p, c, d: "PUSHUP_DEV1_0001.csv"))
    monkeypatch.setattr(phase_mod, "get_file", async_(lambda s, p, f: _entry(uploaded=False)))
    monkeypatch.setattr(phase_mod, "presigned_put_url", lambda b, k, ct, e: f"https://signed/{b}/{k}")

    resp = admin_client.get("/api/v1/ios/phase/presigned-url?class=PUSHUP&deviceId=DEV1")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["filename"] == "PUSHUP_DEV1_0001.csv"
    assert data["csvUrl"].endswith("fitset-collect-imu/ios/PUSHUP/PUSHUP_DEV1_0001.csv")
    assert data["videoUrl"].endswith("fitset-collect-video/ios/PUSHUP/PUSHUP_DEV1_0001.mov")


def test_presigned_url_rejects_bad_input(admin_client):
    assert admin_client.get("/api/v1/ios/phase/presigned-url?class=PLANK&deviceId=DEV1").status_code == 400
    assert admin_client.get("/api/v1/ios/phase/presigned-url?class=SQUAT&deviceId=a/b").status_code == 400


def test_upload_confirm_marks_pending(admin_client, monkeypatch):
    seen = {}
    monkeypatch.setattr(phase_mod, "confirm_collect", async_(lambda s, p, f, vs, rows: seen.update(f=f, vs=vs, rows=rows) or True))
    resp = admin_client.post("/api/v1/ios/phase/upload-confirm",
                             json={"filename": "PUSHUP_DEV1_0001.csv", "videoStart": 1789790030.2, "rows": 2170})
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "pending"
    assert seen == {"f": "PUSHUP_DEV1_0001.csv", "vs": 1789790030.2, "rows": 2170}


def test_upload_confirm_validates(admin_client, monkeypatch):
    monkeypatch.setattr(phase_mod, "confirm_collect", async_(lambda s, p, f, vs, rows: False))
    assert admin_client.post("/api/v1/ios/phase/upload-confirm", json={"filename": "x.csv", "videoStart": 12.0}).status_code == 400
    assert admin_client.post("/api/v1/ios/phase/upload-confirm", json={"filename": "x.csv", "videoStart": 1789790030.2}).status_code == 404


def test_files_lists_with_counts(admin_client, monkeypatch):
    label = PhaseLabelRead(data_bucket="fitset-collect-labeled", data_key="k", video_bucket="fitset-collect-labeled",
                           video_key="v", pose_key="p", phase_summary={"rows": 100}, labeled_at="2026-09-22T01:00:00+00:00")
    monkeypatch.setattr(phase_mod, "list_files", async_(lambda s, p: [
        _entry(), _entry("PUSHUP_DEV1_0002.csv", status="labeled", label=label), _entry("SQUAT_DEV1_0001.csv", "SQUAT", status="failed"),
    ]))
    resp = admin_client.get("/api/v1/ios/phase/files")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["counts"] == {"pending": 1, "labeling": 0, "labeled": 1, "failed": 1, "total": 3}
    labeled = next(f for f in data["files"] if f["status"] == "labeled")
    assert labeled["label"]["videoBucket"] == "fitset-collect-labeled"
    assert labeled["class"] == "PUSHUP"
    assert data["files"][0]["label"] is None


def test_label_accepts_only_labelable(admin_client, monkeypatch):
    monkeypatch.setattr(phase_mod, "list_files", async_(lambda s, p: [
        _entry(), _entry("PUSHUP_DEV1_0002.csv", uploaded=False), _entry("DEADLIFT_DEV1_0001.csv", "DEADLIFT"),
        _entry("PUSHUP_DEV1_0003.csv", status="labeling"),
    ]))
    marked, spawned = [], []
    monkeypatch.setattr(phase_mod, "mark_labeling", async_(lambda s, p, names: marked.extend(names)))
    monkeypatch.setattr(phase_mod, "spawn_worker", lambda p, names: spawned.extend(names))

    resp = admin_client.post("/api/v1/ios/phase/label", json={"filenames": [
        "PUSHUP_DEV1_0001.csv", "PUSHUP_DEV1_0002.csv", "DEADLIFT_DEV1_0001.csv", "PUSHUP_DEV1_0003.csv", "ghost.csv",
    ]})
    assert resp.status_code == 202
    data = resp.json()["data"]
    assert data["accepted"] == ["PUSHUP_DEV1_0001.csv", "DEADLIFT_DEV1_0001.csv"]
    assert {s["filename"]: s["reason"] for s in data["skipped"]} == {
        "PUSHUP_DEV1_0002.csv": "업로드 미완료",
        "PUSHUP_DEV1_0003.csv": "이미 라벨링 중",
        "ghost.csv": "목록에 없는 파일",
    }
    assert marked == spawned == ["PUSHUP_DEV1_0001.csv", "DEADLIFT_DEV1_0001.csv"]


def test_label_spawns_worker_module(monkeypatch):
    calls = {}
    monkeypatch.setattr(phase_mod, "subprocess", SimpleNamespace(Popen=lambda args, **kw: calls.update(args=args)))
    phase_mod.spawn_worker("ios", ["a.csv"])
    assert "app.worker.phase_labeler" in calls["args"] and "ios" in calls["args"]


def test_label_rejects_empty(admin_client):
    assert admin_client.post("/api/v1/ios/phase/label", json={"filenames": []}).status_code == 400


def test_video_url_uses_labeled_bucket_after_labeling(admin_client, monkeypatch):
    label = PhaseLabelRead(data_bucket="fitset-collect-labeled", data_key="k", video_bucket="fitset-collect-labeled",
                           video_key="ios/PUSHUP/PUSHUP_DEV1_0001.mov", pose_key="p", phase_summary={}, labeled_at="2026-09-22T01:00:00+00:00")
    monkeypatch.setattr(phase_mod, "get_file", async_(lambda s, p, f: _entry(status="labeled", label=label) if f == "PUSHUP_DEV1_0001.csv" else None))
    monkeypatch.setattr(phase_mod, "presigned_get_url", lambda b, k, e: f"https://signed/{b}/{k}")

    resp = admin_client.get("/api/v1/ios/phase/video-url?filename=PUSHUP_DEV1_0001.csv")
    assert resp.status_code == 200
    assert resp.json()["data"]["url"] == "https://signed/fitset-collect-labeled/ios/PUSHUP/PUSHUP_DEV1_0001.mov"
    assert admin_client.get("/api/v1/ios/phase/video-url?filename=ghost.csv").status_code == 404


def test_pose_404_before_labeling(admin_client, monkeypatch):
    monkeypatch.setattr(phase_mod, "get_file", async_(lambda s, p, f: _entry()))
    assert admin_client.get("/api/v1/ios/phase/pose?filename=PUSHUP_DEV1_0001.csv").status_code == 404


def test_pose_returns_frames(admin_client, monkeypatch):
    label = PhaseLabelRead(data_bucket="b", data_key="k", video_bucket="b", video_key="v", pose_key="p",
                           phase_summary={}, labeled_at="2026-09-22T01:00:00+00:00")
    monkeypatch.setattr(phase_mod, "get_file", async_(lambda s, p, f: _entry(status="labeled", label=label)))
    monkeypatch.setattr(phase_mod, "read_pose", lambda b, k: {"fps": 30.0, "frames": [[0, [[0.1, 0.2, 0.9]] * 33], [-1, None]]})
    resp = admin_client.get("/api/v1/ios/phase/pose?filename=PUSHUP_DEV1_0001.csv")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["fps"] == 30.0 and len(data["frames"]) == 2 and data["frames"][1] == [-1, None]


def test_phase_requires_basic(client):
    assert client.get("/api/v1/ios/phase/files").status_code == 401


def _label():
    return PhaseLabelRead(data_bucket="fitset-collect-labeled", data_key="ios/PUSHUP/PUSHUP_DEV1_0001.parquet",
                          video_bucket="fitset-collect-labeled", video_key="v", pose_key="p", phase_summary={"rows": 100, "hasPhase": True},
                          labeled_at="2026-09-22T01:00:00+00:00")


def _dataset(filename="PUSHUP_DEV1_0001.parquet"):
    return DatasetFileRead(id=7, filename=filename, class_name="PUSHUP", device_id="DEV1", bucket="fitset-dataset",
                           s3_key=f"ios/raw/PUSHUP/{filename}", uploaded=True, phase_labeled=True,
                           created_at="2026-09-22T02:00:00+00:00")


def test_promote_copies_label_and_skips_others(admin_client, monkeypatch):
    monkeypatch.setattr(phase_mod, "list_files", async_(lambda s, p: [
        _entry(status="labeled", label=_label()),
        _entry("PUSHUP_DEV1_0002.csv"),
        _entry("PUSHUP_DEV1_0003.csv", status="labeled", label=_label()).model_copy(update={"dataset_file": _dataset("PUSHUP_DEV1_0003.parquet")}),
        _entry("DEADLIFT_DEV1_0001.csv", "DEADLIFT"),
    ]))
    rows = []
    monkeypatch.setattr(phase_mod, "_copy_to_dataset", lambda e, key: key)
    monkeypatch.setattr(phase_mod, "promote_row", async_(lambda s, p, name, **kw: rows.append((name, kw)) or _dataset()))

    resp = admin_client.post("/api/v1/ios/phase/promote", json={"filenames": [
        "PUSHUP_DEV1_0001.csv", "PUSHUP_DEV1_0002.csv", "PUSHUP_DEV1_0003.csv", "DEADLIFT_DEV1_0001.csv", "ghost.csv",
    ]})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["promoted"] == ["PUSHUP_DEV1_0001.csv", "PUSHUP_DEV1_0002.csv", "DEADLIFT_DEV1_0001.csv"]
    assert {s["filename"]: s["reason"] for s in data["skipped"]} == {"PUSHUP_DEV1_0003.csv": "이미 승격됨", "ghost.csv": "목록에 없는 파일"}
    flags = {name: kw["phase_labeled"] for name, kw in rows}
    assert flags == {"PUSHUP_DEV1_0001.csv": True, "PUSHUP_DEV1_0002.csv": False, "DEADLIFT_DEV1_0001.csv": False}


def test_train_validates_class_and_files(admin_client, monkeypatch):
    assert admin_client.post("/api/v1/ios/phase/train", json={"class": "DEADLIFT"}).status_code == 400
    monkeypatch.setattr(phase_mod, "phase_labeled_files", async_(lambda s, p, c: []))
    resp = admin_client.post("/api/v1/ios/phase/train", json={"class": "PUSHUP"})
    assert resp.status_code == 400 and "phase 라벨 파일이 없습니다" in resp.json()["error"]["message"]


def test_train_creates_model_and_spawns(admin_client, monkeypatch):
    monkeypatch.setattr(phase_mod, "phase_labeled_files", async_(lambda s, p, c: [_dataset(), _dataset("PUSHUP_DEV1_0002.parquet")]))
    monkeypatch.setattr(phase_mod, "phase_model_versions", async_(lambda s, p, c: ["v1.0", "v1.1"]))
    created, spawned = {}, {}
    def fake_create(s, p, c, version, files, **kw):
        created.update(version=version, files=files, **kw)
        return PhaseModelRead(id=3, platform=p, class_name=c, version=version, bucket="fitset-phase-models",
                              created_at="2026-09-22T03:00:00+00:00")
    monkeypatch.setattr(phase_mod, "create_phase_model", async_(fake_create))
    monkeypatch.setattr(phase_mod, "spawn_trainer", lambda *a, **kw: spawned.update(args=a, kw=kw))

    resp = admin_client.post("/api/v1/ios/phase/train", json={"class": "PUSHUP", "epochs": 5})
    assert resp.status_code == 202
    data = resp.json()["data"]
    assert data == {"modelId": 3, "version": "v1.2", "class": "PUSHUP", "numFiles": 2}
    assert created["files"] == ["PUSHUP_DEV1_0001.parquet", "PUSHUP_DEV1_0002.parquet"] and created["epochs"] == 5 and created["lr"] == 0.001
    assert spawned["args"][2] == 3 and spawned["kw"]["window"] == 50


def test_models_list_and_download_url(admin_client, monkeypatch):
    model = PhaseModelRead(id=3, platform="ios", class_name="PUSHUP", version="v1.0", status="completed",
                           bucket="fitset-phase-models", pt_key="ios/PUSHUP/v1.0/FitSetPhase.pt", onnx_key=None,
                           metrics={"final": {"macro_f1": 0.9}}, created_at="2026-09-22T03:00:00+00:00")
    monkeypatch.setattr(phase_mod, "list_phase_models", async_(lambda s, p, c=None: [model]))
    monkeypatch.setattr(phase_mod, "get_phase_model", async_(lambda s, p, i: model if i == 3 else None))
    monkeypatch.setattr(phase_mod, "presigned_get_url", lambda b, k, e: f"https://signed/{b}/{k}")

    resp = admin_client.get("/api/v1/ios/phase/models?class=PUSHUP")
    assert resp.status_code == 200
    assert resp.json()["data"]["models"][0]["class"] == "PUSHUP"
    assert resp.json()["data"]["models"][0]["canDownload"] is True
    assert resp.json()["data"]["models"][0]["metrics"]["final"]["macro_f1"] == 0.9

    ok = admin_client.get("/api/v1/ios/phase/models/3/download-url?format=pt")
    assert ok.status_code == 200 and ok.json()["data"]["url"].endswith("FitSetPhase.pt")
    assert admin_client.get("/api/v1/ios/phase/models/3/download-url?format=onnx").status_code == 404
    assert admin_client.get("/api/v1/ios/phase/models/9/download-url?format=pt").status_code == 404
    assert admin_client.get("/api/v1/ios/phase/models/3/download-url?format=tflite").status_code == 400


def test_computed_flags_in_files_response(admin_client, monkeypatch):
    monkeypatch.setattr(phase_mod, "list_files", async_(lambda s, p: [
        _entry(),
        _entry("PUSHUP_DEV1_0002.csv", status="labeled", label=_label()),
        _entry("DEADLIFT_DEV1_0001.csv", "DEADLIFT"),
        _entry("PUSHUP_DEV1_0003.csv", uploaded=False),
    ]))
    files = {f["filename"]: f for f in admin_client.get("/api/v1/ios/phase/files").json()["data"]["files"]}
    assert files["PUSHUP_DEV1_0001.csv"]["canLabel"] and files["PUSHUP_DEV1_0001.csv"]["canPromote"]
    assert not files["PUSHUP_DEV1_0002.csv"]["canLabel"] and files["PUSHUP_DEV1_0002.csv"]["canPromote"]
    assert files["PUSHUP_DEV1_0002.csv"]["label"]["hasPhase"] is True
    assert files["DEADLIFT_DEV1_0001.csv"]["canLabel"] and files["DEADLIFT_DEV1_0001.csv"]["canPromote"]
    assert not files["PUSHUP_DEV1_0003.csv"]["canLabel"] and not files["PUSHUP_DEV1_0003.csv"]["canPromote"]


def test_label_request_dedups_filenames(admin_client, monkeypatch):
    monkeypatch.setattr(phase_mod, "list_files", async_(lambda s, p: [_entry()]))
    marked = []
    monkeypatch.setattr(phase_mod, "mark_labeling", async_(lambda s, p, names: marked.extend(names)))
    monkeypatch.setattr(phase_mod, "spawn_worker", lambda p, names: None)
    resp = admin_client.post("/api/v1/ios/phase/label", json={"filenames": ["PUSHUP_DEV1_0001.csv", "", "PUSHUP_DEV1_0001.csv"]})
    assert resp.status_code == 202 and marked == ["PUSHUP_DEV1_0001.csv"]


def test_label_rep_count_estimate_from_summary(admin_client, monkeypatch):
    label = _label().model_copy(update={"phase_summary": {"rows": 100, "repCount": 14}})
    monkeypatch.setattr(phase_mod, "list_files", async_(lambda s, p: [_entry(status="labeled", label=label), _entry(status="labeled", label=_label())]))
    files = admin_client.get("/api/v1/ios/phase/files").json()["data"]["files"]
    assert files[0]["label"]["repCountEstimate"] == 14 and files[1]["label"]["repCountEstimate"] is None
