import io
import pathlib
from types import SimpleNamespace

from conftest import async_
import app.labeling.service as labeling_mod
from app.data.models import DatasetFileRead
from app.labeling.models import CollectFileRead, PhaseLabelRead


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
    monkeypatch.setattr(labeling_mod, "reserve_collect", async_(lambda s, p, c, d: "PUSHUP_DEV1_0001.csv"))
    monkeypatch.setattr(labeling_mod, "get_file", async_(lambda s, p, f: _entry(uploaded=False)))
    monkeypatch.setattr(labeling_mod, "presigned_put_url", lambda b, k, ct, e: f"https://signed/{b}/{k}")

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
    monkeypatch.setattr(labeling_mod, "confirm_collect", async_(lambda s, p, f, vs, rows: seen.update(f=f, vs=vs, rows=rows) or True))
    resp = admin_client.post("/api/v1/ios/phase/upload-confirm",
                             json={"filename": "PUSHUP_DEV1_0001.csv", "videoStart": 1789790030.2, "rows": 2170})
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "pending"
    assert seen == {"f": "PUSHUP_DEV1_0001.csv", "vs": 1789790030.2, "rows": 2170}


def test_upload_confirm_validates(admin_client, monkeypatch):
    monkeypatch.setattr(labeling_mod, "confirm_collect", async_(lambda s, p, f, vs, rows: False))
    assert admin_client.post("/api/v1/ios/phase/upload-confirm", json={"filename": "x.csv", "videoStart": 12.0}).status_code == 400
    assert admin_client.post("/api/v1/ios/phase/upload-confirm", json={"filename": "x.csv", "videoStart": 1789790030.2}).status_code == 404


def test_files_lists_with_counts(admin_client, monkeypatch):
    label = PhaseLabelRead(data_bucket="fitset-collect-labeled", data_key="k", video_bucket="fitset-collect-labeled",
                           video_key="v", pose_key="p", phase_summary={"rows": 100}, labeled_at="2026-09-22T01:00:00+00:00")
    monkeypatch.setattr(labeling_mod, "list_files", async_(lambda s, p: [
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
    monkeypatch.setattr(labeling_mod, "list_files", async_(lambda s, p: [
        _entry(), _entry("PUSHUP_DEV1_0002.csv", uploaded=False), _entry("DEADLIFT_DEV1_0001.csv", "DEADLIFT"),
        _entry("PUSHUP_DEV1_0003.csv", status="labeling"),
    ]))
    marked, spawned = [], []
    monkeypatch.setattr(labeling_mod, "mark_labeling", async_(lambda s, p, names: marked.extend(names)))
    monkeypatch.setattr(labeling_mod, "spawn_worker", lambda p, names: spawned.extend(names))

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
    monkeypatch.setattr(labeling_mod, "subprocess", SimpleNamespace(Popen=lambda args, **kw: calls.update(args=args)))
    labeling_mod.spawn_worker("ios", ["a.csv"])
    assert "app.labeling.worker" in calls["args"] and "ios" in calls["args"]


def test_label_rejects_empty(admin_client):
    assert admin_client.post("/api/v1/ios/phase/label", json={"filenames": []}).status_code == 400


def test_video_url_uses_labeled_bucket_after_labeling(admin_client, monkeypatch):
    label = PhaseLabelRead(data_bucket="fitset-collect-labeled", data_key="k", video_bucket="fitset-collect-labeled",
                           video_key="ios/PUSHUP/PUSHUP_DEV1_0001.mov", pose_key="p", phase_summary={}, labeled_at="2026-09-22T01:00:00+00:00")
    monkeypatch.setattr(labeling_mod, "get_file", async_(lambda s, p, f: _entry(status="labeled", label=label) if f == "PUSHUP_DEV1_0001.csv" else None))
    monkeypatch.setattr(labeling_mod, "presigned_get_url", lambda b, k, e: f"https://signed/{b}/{k}")

    resp = admin_client.get("/api/v1/ios/phase/video-url?filename=PUSHUP_DEV1_0001.csv")
    assert resp.status_code == 200
    assert resp.json()["data"]["url"] == "https://signed/fitset-collect-labeled/ios/PUSHUP/PUSHUP_DEV1_0001.mov"
    assert admin_client.get("/api/v1/ios/phase/video-url?filename=ghost.csv").status_code == 404


def test_pose_404_before_labeling(admin_client, monkeypatch):
    monkeypatch.setattr(labeling_mod, "get_file", async_(lambda s, p, f: _entry()))
    assert admin_client.get("/api/v1/ios/phase/pose?filename=PUSHUP_DEV1_0001.csv").status_code == 404


def test_pose_returns_frames(admin_client, monkeypatch):
    label = PhaseLabelRead(data_bucket="b", data_key="k", video_bucket="b", video_key="v", pose_key="p",
                           phase_summary={}, labeled_at="2026-09-22T01:00:00+00:00")
    monkeypatch.setattr(labeling_mod, "get_file", async_(lambda s, p, f: _entry(status="labeled", label=label)))
    monkeypatch.setattr(labeling_mod, "read_pose", lambda b, k: {"fps": 30.0, "frames": [[0, [[0.1, 0.2, 0.9]] * 33], [-1, None]]})
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
    monkeypatch.setattr(labeling_mod, "list_files", async_(lambda s, p: [
        _entry(status="labeled", label=_label()),
        _entry("PUSHUP_DEV1_0002.csv"),
        _entry("PUSHUP_DEV1_0003.csv", status="labeled", label=_label()).model_copy(update={"dataset_file": _dataset("PUSHUP_DEV1_0003.parquet")}),
        _entry("DEADLIFT_DEV1_0001.csv", "DEADLIFT"),
    ]))
    rows = []
    monkeypatch.setattr(labeling_mod, "_copy_to_dataset", lambda e, key: key)
    monkeypatch.setattr(labeling_mod, "reserve_promotion", async_(lambda s, p, name, **kw: rows.append((name, kw)) or _dataset()))
    monkeypatch.setattr(labeling_mod, "complete_promotion", async_(lambda s, p, name: None))

    resp = admin_client.post("/api/v1/ios/phase/promote", json={"filenames": [
        "PUSHUP_DEV1_0001.csv", "PUSHUP_DEV1_0002.csv", "PUSHUP_DEV1_0003.csv", "DEADLIFT_DEV1_0001.csv", "ghost.csv",
    ]})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["promoted"] == ["PUSHUP_DEV1_0001.csv", "PUSHUP_DEV1_0002.csv", "DEADLIFT_DEV1_0001.csv"]
    assert {s["filename"]: s["reason"] for s in data["skipped"]} == {"PUSHUP_DEV1_0003.csv": "이미 승격됨", "ghost.csv": "목록에 없는 파일"}
    flags = {name: kw["phase_labeled"] for name, kw in rows}
    assert flags == {"PUSHUP_DEV1_0001.csv": True, "PUSHUP_DEV1_0002.csv": False, "DEADLIFT_DEV1_0001.csv": False}


def test_promote_s3_failure_skips_and_retry_resumes(admin_client, monkeypatch):
    pending = _dataset().model_copy(update={"uploaded": False})
    entry = _entry(status="labeled", label=_label()).model_copy(update={"dataset_file": pending})
    monkeypatch.setattr(labeling_mod, "list_files", async_(lambda s, p: [entry]))
    monkeypatch.setattr(labeling_mod, "reserve_promotion", async_(lambda s, p, name, **kw: pending))
    completed = []
    monkeypatch.setattr(labeling_mod, "complete_promotion", async_(lambda s, p, name: completed.append(name)))

    def boom(e, key):
        raise OSError("s3 down")
    monkeypatch.setattr(labeling_mod, "_copy_to_dataset", boom)
    data = admin_client.post("/api/v1/ios/phase/promote", json={"filenames": ["PUSHUP_DEV1_0001.csv"]}).json()["data"]
    assert data["promoted"] == [] and "다시 승격" in data["skipped"][0]["reason"] and completed == []

    copied = []
    monkeypatch.setattr(labeling_mod, "_copy_to_dataset", lambda e, key: copied.append(key) or key)
    data = admin_client.post("/api/v1/ios/phase/promote", json={"filenames": ["PUSHUP_DEV1_0001.csv"]}).json()["data"]
    assert data["promoted"] == ["PUSHUP_DEV1_0001.csv"] and completed == ["PUSHUP_DEV1_0001.csv"]
    assert copied == [pending.s3_key]


def test_computed_flags_in_files_response(admin_client, monkeypatch):
    monkeypatch.setattr(labeling_mod, "list_files", async_(lambda s, p: [
        _entry(),
        _entry("PUSHUP_DEV1_0002.csv", status="labeled", label=_label()),
        _entry("DEADLIFT_DEV1_0001.csv", "DEADLIFT"),
        _entry("PUSHUP_DEV1_0003.csv", uploaded=False),
    ]))
    files = {f["filename"]: f for f in admin_client.get("/api/v1/ios/phase/files").json()["data"]["files"]}
    assert files["PUSHUP_DEV1_0001.csv"]["canLabel"] and files["PUSHUP_DEV1_0001.csv"]["canPromote"]
    assert files["PUSHUP_DEV1_0002.csv"]["canLabel"] and files["PUSHUP_DEV1_0002.csv"]["canPromote"]
    assert files["PUSHUP_DEV1_0002.csv"]["label"]["hasPhase"] is True
    assert files["DEADLIFT_DEV1_0001.csv"]["canLabel"] and files["DEADLIFT_DEV1_0001.csv"]["canPromote"]
    assert not files["PUSHUP_DEV1_0003.csv"]["canLabel"] and not files["PUSHUP_DEV1_0003.csv"]["canPromote"]


def test_label_request_dedups_filenames(admin_client, monkeypatch):
    monkeypatch.setattr(labeling_mod, "list_files", async_(lambda s, p: [_entry()]))
    marked = []
    monkeypatch.setattr(labeling_mod, "mark_labeling", async_(lambda s, p, names: marked.extend(names)))
    monkeypatch.setattr(labeling_mod, "spawn_worker", lambda p, names: None)
    resp = admin_client.post("/api/v1/ios/phase/label", json={"filenames": ["PUSHUP_DEV1_0001.csv", "", "PUSHUP_DEV1_0001.csv"]})
    assert resp.status_code == 202 and marked == ["PUSHUP_DEV1_0001.csv"]


def test_label_rep_count_estimate_from_summary(admin_client, monkeypatch):
    label = _label().model_copy(update={"phase_summary": {"rows": 100, "repCount": 14}})
    monkeypatch.setattr(labeling_mod, "list_files", async_(lambda s, p: [_entry(status="labeled", label=label), _entry(status="labeled", label=_label())]))
    files = admin_client.get("/api/v1/ios/phase/files").json()["data"]["files"]
    assert files[0]["label"]["repCountEstimate"] == 14 and files[1]["label"]["repCountEstimate"] is None


def test_delete_removes_objects_and_row(admin_client, monkeypatch):
    label = PhaseLabelRead(data_bucket="fitset-collect-labeled", data_key="d", video_bucket="fitset-collect-labeled",
                           video_key="v", pose_key="p", phase_summary={}, labeled_at="2026-09-22T01:00:00+00:00")
    files = {"PUSHUP_DEV1_0001.csv": _entry(status="labeled", label=label), "PUSHUP_DEV1_0002.csv": _entry("PUSHUP_DEV1_0002.csv", status="labeling")}
    deleted, removed = [], []
    monkeypatch.setattr(labeling_mod, "get_file", async_(lambda s, p, f: files.get(f)))
    monkeypatch.setattr(labeling_mod.s3, "delete_object", lambda b, k: deleted.append((b, k)))
    monkeypatch.setattr(labeling_mod, "delete_collect", async_(lambda s, p, f: removed.append(f)))

    resp = admin_client.delete("/api/v1/ios/phase/files?filename=PUSHUP_DEV1_0001.csv")
    assert resp.status_code == 200
    assert removed == ["PUSHUP_DEV1_0001.csv"]
    assert ("fitset-collect-imu", "ios/PUSHUP/PUSHUP_DEV1_0001.csv") in deleted
    assert ("fitset-collect-labeled", "p") in deleted and len(deleted) == 5

    assert admin_client.delete("/api/v1/ios/phase/files?filename=PUSHUP_DEV1_0002.csv").status_code == 409
    assert admin_client.delete("/api/v1/ios/phase/files?filename=nope.csv").status_code == 404
    assert removed == ["PUSHUP_DEV1_0001.csv"]


def test_change_class_rewrites_label_and_blocks_after_promotion(admin_client, monkeypatch, tmp_path):
    import pandas as pd

    labeled = PhaseLabelRead(data_bucket="fitset-collect-labeled", data_key="ios/PUSHUP/PUSHUP_DEV1_0004.parquet",
                             video_bucket="fitset-collect-labeled", video_key="ios/PUSHUP/PUSHUP_DEV1_0004.mov", pose_key="p",
                             phase_summary={}, labeled_at="2026-09-22T01:00:00+00:00")
    promoted = _entry("PUSHUP_DEV1_0002.csv")
    promoted.dataset_file = _dataset()
    files = {"PUSHUP_DEV1_0001.csv": _entry(), "PUSHUP_DEV1_0002.csv": promoted,
             "PUSHUP_DEV1_0003.csv": _entry("PUSHUP_DEV1_0003.csv", status="labeling"),
             "PUSHUP_DEV1_0004.csv": _entry("PUSHUP_DEV1_0004.csv", status="labeled", label=labeled)}
    table = pd.DataFrame({"timestamp": [1.5, 1.51], "ax": [0.1, 0.2], "label": ["PUSHUP", "PUSHUP"]})
    store = {("fitset-collect-imu", "ios/PUSHUP/PUSHUP_DEV1_0001.csv"): table.to_csv(index=False).encode(),
             ("fitset-collect-labeled", "ios/PUSHUP/PUSHUP_DEV1_0004.parquet"): table.assign(phase=[0, 1]).to_parquet(index=False)}
    copied, deleted = [], []

    def download(b, k, path):
        pathlib.Path(path).write_bytes(store[(b, k)])

    def upload(b, k, path, ct):
        store[(b, k)] = pathlib.Path(path).read_bytes()

    monkeypatch.setattr(labeling_mod, "get_file", async_(lambda s, p, f: files.get(f)))
    monkeypatch.setattr(labeling_mod, "change_collect_class", async_(lambda s, p, f, c: _entry(f.replace("PUSHUP", "SQUAT"), "SQUAT")))
    monkeypatch.setattr(labeling_mod.s3, "download_object", download)
    monkeypatch.setattr(labeling_mod.s3, "upload_object", upload)
    monkeypatch.setattr(labeling_mod.s3, "copy_object", lambda b, k, db, dk: copied.append((b, k, dk)))
    monkeypatch.setattr(labeling_mod.s3, "delete_object", lambda b, k: deleted.append((b, k)))
    patch = lambda f, c="SQUAT": admin_client.patch("/api/v1/ios/phase/files/class", json={"filename": f, "class": c})

    resp = patch("PUSHUP_DEV1_0001.csv")
    assert resp.status_code == 200 and resp.json()["data"]["filename"] == "SQUAT_DEV1_0001.csv"
    out = pd.read_csv(io.BytesIO(store[("fitset-collect-imu", "ios/SQUAT/SQUAT_DEV1_0001.csv")]))
    assert list(out["label"]) == ["SQUAT", "SQUAT"] and list(out["ax"]) == [0.1, 0.2]
    assert copied == [("fitset-collect-video", "ios/PUSHUP/PUSHUP_DEV1_0001.mov", "ios/SQUAT/SQUAT_DEV1_0001.mov")]
    assert ("fitset-collect-imu", "ios/PUSHUP/PUSHUP_DEV1_0001.csv") in deleted

    assert patch("PUSHUP_DEV1_0004.csv").status_code == 200
    out = pd.read_csv(io.BytesIO(store[("fitset-collect-imu", "ios/SQUAT/SQUAT_DEV1_0004.csv")]))
    assert "phase" not in out.columns and set(out["label"]) == {"SQUAT"}
    assert copied[-1] == ("fitset-collect-labeled", "ios/PUSHUP/PUSHUP_DEV1_0004.mov", "ios/SQUAT/SQUAT_DEV1_0004.mov")
    assert ("fitset-collect-labeled", "p") in deleted

    assert patch("PUSHUP_DEV1_0002.csv").status_code == 409
    assert patch("PUSHUP_DEV1_0003.csv").status_code == 409
    assert patch("nope.csv").status_code == 404
    assert patch("PUSHUP_DEV1_0001.csv", "PLANK").status_code == 400
    assert len(copied) == 2


def test_edit_phases_rewrites_label(admin_client, monkeypatch):
    label = PhaseLabelRead(data_bucket="b", data_key="k", video_bucket="b", video_key="v", pose_key="p",
                           phase_summary={"fps": 30.0, "repCount": 0}, labeled_at="2026-09-22T01:00:00+00:00")
    monkeypatch.setattr(labeling_mod, "get_file", async_(lambda s, p, f: _entry(status="labeled", label=label)))
    monkeypatch.setattr(labeling_mod, "read_pose", lambda b, k: {"fps": 30.0, "frames": [[2, None]] * 4})
    written, saved = {}, {}
    monkeypatch.setattr(labeling_mod, "_rewrite_phases", lambda e, pose, phases: written.update(phases=phases) or [0, 0, 1, 1])
    monkeypatch.setattr(labeling_mod, "update_phase_summary", async_(lambda s, p, f, summary: saved.update(summary)))

    resp = admin_client.patch("/api/v1/ios/phase/files/phases", json={"filename": "PUSHUP_DEV1_0001.csv", "phases": [0, 0, 1, 1]})
    assert resp.status_code == 200
    assert written["phases"] == [0, 0, 1, 1]
    assert saved["repCount"] == 1 and saved["rowPhaseCounts"] == {"0": 2, "1": 2} and saved["edited"] is True

    assert admin_client.patch("/api/v1/ios/phase/files/phases", json={"filename": "PUSHUP_DEV1_0001.csv", "phases": [0, 1]}).status_code == 409
    assert admin_client.patch("/api/v1/ios/phase/files/phases", json={"filename": "PUSHUP_DEV1_0001.csv", "phases": [0, 5, 1, 1]}).status_code in (400, 422)


def test_relabel_reads_labeled_objects_and_refreshes_promoted_copy(monkeypatch, tmp_path):
    import numpy as np
    import pandas as pd
    import app.labeling.worker as worker

    entry = _entry(status="labeled", label=_label()).model_copy(update={"dataset_file": _dataset()})
    src = pd.DataFrame({"timestamp": [1789790030.2 + i / 30 for i in range(4)], "ax": 0.0, "phase": 2})
    ops = []

    def download(bucket, key, path):
        ops.append(("get", bucket, key))
        if key.endswith(".parquet"):
            src.to_parquet(path)
    monkeypatch.setattr(worker.s3, "download_object", download)
    monkeypatch.setattr(worker.s3, "upload_object", lambda b, k, p, t: ops.append(("put", b, k)))
    monkeypatch.setattr(worker.s3, "copy_object", lambda sb, k, db_, dk=None: ops.append(("copy", sb, k, db_, dk)))
    monkeypatch.setattr(worker.s3, "delete_object", lambda b, k: ops.append(("del", b, k)))
    monkeypatch.setattr(worker.db, "run", lambda coro: coro.close())
    monkeypatch.setattr(worker, "extract_pose", lambda path, motion: (np.full(4, np.nan), [None] * 4, 30.0))

    result = worker.label_file("ios", entry, str(tmp_path))
    worker.move_to_labeled("ios", entry, result)
    assert ("get", "fitset-collect-labeled", entry.label.data_key) in ops and ("get", "fitset-collect-labeled", "v") in ops
    assert not any(op[0] == "del" for op in ops)
    assert [op for op in ops if op[0] == "copy"] == [("copy", "fitset-collect-labeled", result["data_key"], "fitset-dataset", _dataset().s3_key)]


def test_imu_returns_seconds_from_video_start(admin_client, monkeypatch, tmp_path):
    import pandas as pd

    label = PhaseLabelRead(data_bucket="b", data_key="k", video_bucket="b", video_key="v", pose_key="p",
                           phase_summary={}, labeled_at="2026-09-22T01:00:00+00:00")
    monkeypatch.setattr(labeling_mod, "get_file", async_(lambda s, p, f: _entry(status="labeled", label=label, video_start=1000.0)))
    pd.DataFrame({"timestamp": [1000.5, 1000.51], **{c: [1.0, 2.0] for c in ["ax", "ay", "az", "gx", "gy", "gz"]}}).to_parquet(tmp_path / "d.parquet")
    monkeypatch.setattr(labeling_mod.s3, "download_object", lambda b, k, dst: pathlib.Path(dst).write_bytes((tmp_path / "d.parquet").read_bytes()))

    resp = admin_client.get("/api/v1/ios/phase/imu?filename=PUSHUP_DEV1_0001.csv")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["t"] == [0.5, 0.51] and data["channels"]["gz"] == [1.0, 2.0]
    monkeypatch.setattr(labeling_mod, "get_file", async_(lambda s, p, f: _entry()))
    assert admin_client.get("/api/v1/ios/phase/imu?filename=PUSHUP_DEV1_0001.csv").status_code == 404
