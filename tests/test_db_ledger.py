from sqlmodel import select

import app.data.repository as data_repo
import app.phase.repository as phase_repo
import app.training.repository as train_repo
from app.core import db
from app.core.models import ensure_device, ensure_platform
from app.data.models import DatasetFile
from app.phase.models import CollectFile, PhaseLabel


def run(fn, *args, **kwargs):
    """repository 코루틴을 독립 세션(요청 하나에 해당)으로 실행하고 commit 한다"""
    async def go():
        async with db.session() as s:
            return await fn(s, *args, **kwargs)
    return db.run(go())


def query(stmt):
    """세션 하나 열어 select 결과 목록"""
    async def go():
        async with db.session() as s:
            return (await s.exec(stmt)).all()
    return db.run(go())


def test_reserve_numbers_per_device_and_platform(fresh_db):
    assert run(data_repo.reserve_admin_upload, "ios", "SQUAT", "DEV1") == ("SQUAT_DEV1_0001.csv", "ios/raw/000_SQUAT/SQUAT_DEV1_0001.csv")
    assert run(data_repo.reserve_admin_upload, "ios", "SQUAT", "DEV1")[0] == "SQUAT_DEV1_0002.csv"
    assert run(data_repo.reserve_admin_upload, "ios", "SQUAT", "DEV2")[0] == "SQUAT_DEV2_0001.csv"
    assert run(data_repo.reserve_admin_upload, "android", "SQUAT", "DEV1")[0] == "SQUAT_DEV1_0001.csv"

    files = run(data_repo.list_files, "ios")
    assert [f.filename for f in files] == ["SQUAT_DEV1_0001.csv", "SQUAT_DEV1_0002.csv", "SQUAT_DEV2_0001.csv"]
    assert files[0].uploaded is False
    assert files[0].s3_key == "ios/raw/000_SQUAT/SQUAT_DEV1_0001.csv"
    assert files[0].device_id == "DEV1"


def test_relationships_back_populate(fresh_db):
    async def make():
        async with db.session() as s:
            platform = await ensure_platform(s, "ios")
            device = await ensure_device(s, platform, "DEV1")
            assert device.platform is platform
            assert platform.devices == [device]
    db.run(make())
    f1 = run(data_repo.reserve_admin_upload, "ios", "SQUAT", "DEV1")[0]
    c1 = run(phase_repo.reserve_collect, "ios", "PUSHUP", "DEV1")
    dataset = query(select(DatasetFile).where(DatasetFile.filename == f1))[0]
    collect = query(select(CollectFile).where(CollectFile.filename == c1))[0]
    assert dataset.platform.name == "ios" and dataset.device.device_id == "DEV1"
    assert collect.platform.name == dataset.platform.name and collect.device.device_id == dataset.device.device_id
    assert collect.label is None


def test_upload_confirm_and_training_view(fresh_db):
    f1 = run(data_repo.reserve_admin_upload, "ios", "SQUAT", "DEV1")[0]
    f2 = run(data_repo.reserve_admin_upload, "ios", "PUSHUP", "DEV1")[0]
    assert run(data_repo.mark_admin_uploaded, "ios", f1) is True
    assert run(data_repo.mark_admin_uploaded, "ios", "ghost.csv") is False

    assert run(train_repo.uploaded_filenames, "ios") == {f1}
    assert run(data_repo.dataset_file_classes, "ios", [f1, f2]) == {f1: "SQUAT", f2: "PUSHUP"}

    run(data_repo.mark_trained, "ios", [f1], "v1.5")
    by_name = {f.filename: f.trained_in_version for f in run(data_repo.list_files, "ios")}
    assert by_name == {f1: "v1.5", f2: None}


def test_collect_lifecycle_to_labeled(fresh_db):
    name = run(phase_repo.reserve_collect, "ios", "PUSHUP", "DEV1")
    entry = run(phase_repo.get_file, "ios", name)
    assert entry.status == "pending" and entry.uploaded is False
    assert entry.csv_key == "ios/001_PUSHUP/PUSHUP_DEV1_0001.csv"
    assert entry.video_key == "ios/001_PUSHUP/PUSHUP_DEV1_0001.mov"

    assert run(phase_repo.confirm_collect, "ios", name, 1789790030.2, 2170) is True
    assert run(phase_repo.confirm_collect, "ios", "ghost.csv", 1.0, None) is False
    run(phase_repo.mark_labeling, "ios", [name])
    assert run(phase_repo.get_file, "ios", name).status == "labeling"

    run(phase_repo.finish_label, 
        "ios", name,
        data_bucket="fitset-collect-labeled", data_key="ios/PUSHUP/PUSHUP_DEV1_0001.parquet",
        video_bucket="fitset-collect-labeled", video_key=entry.video_key,
        pose_key="ios/PUSHUP/PUSHUP_DEV1_0001.pose.json",
        phase_summary={"rows": 2170, "rowPhaseCounts": {"0": 900, "1": 1000, "2": 270}},
    )
    done = run(phase_repo.get_file, "ios", name)
    assert done.status == "labeled"
    assert done.label.video_bucket == "fitset-collect-labeled"
    assert done.label.phase_summary["rowPhaseCounts"]["2"] == 270
    row = query(select(CollectFile).where(CollectFile.filename == name))[0]
    label = query(select(PhaseLabel).where(PhaseLabel.collect_file_id == row.id))[0]
    assert label.collect_file_id == row.id and row.label.id == label.id

    run(phase_repo.set_status, "ios", name, "failed", "boom")
    assert run(phase_repo.get_file, "ios", name).error == "boom"


def test_promote_and_phase_model_lifecycle(fresh_db):
    name = run(phase_repo.reserve_collect, "ios", "PUSHUP", "DEV1")
    run(phase_repo.confirm_collect, "ios", name, 1789790030.2, 2170)
    run(phase_repo.finish_label, 
        "ios", name, data_bucket="fitset-collect-labeled", data_key="ios/PUSHUP/PUSHUP_DEV1_0001.parquet",
        video_bucket="fitset-collect-labeled", video_key="v", pose_key="p", phase_summary={"rows": 2170},
    )
    promote_kw = dict(dataset_filename="PUSHUP_DEV1_0001.parquet", bucket="fitset-dataset",
                      key="ios/raw/PUSHUP/PUSHUP_DEV1_0001.parquet", phase_labeled=True)
    dataset = run(phase_repo.reserve_promotion, "ios", name, **promote_kw)
    assert dataset.filename == "PUSHUP_DEV1_0001.parquet" and not dataset.uploaded and dataset.phase_labeled
    assert run(phase_repo.get_file, "ios", name).promoted_at is None
    assert run(phase_repo.phase_labeled_files, "ios", "PUSHUP") == []
    assert "PUSHUP_DEV1_0001.parquet" not in run(train_repo.uploaded_filenames, "ios")
    assert run(phase_repo.reserve_promotion, "ios", name, **promote_kw).id == dataset.id
    run(phase_repo.complete_promotion, "ios", name)
    entry = run(phase_repo.get_file, "ios", name)
    assert entry.dataset_file.id == dataset.id and entry.promoted_at is not None
    assert [f.filename for f in run(data_repo.list_files, "ios")] == ["PUSHUP_DEV1_0001.parquet"]
    assert [f.filename for f in run(phase_repo.phase_labeled_files, "ios", "PUSHUP")] == ["PUSHUP_DEV1_0001.parquet"]
    assert run(data_repo.dataset_locations, "ios", ["PUSHUP_DEV1_0001.parquet"]) == {
        "PUSHUP_DEV1_0001.parquet": ("fitset-dataset", "ios/raw/PUSHUP/PUSHUP_DEV1_0001.parquet")}

    model = run(phase_repo.create_phase_model, "ios", "PUSHUP", "v1.0", ["PUSHUP_DEV1_0001.parquet"], window=50, stride=5, epochs=3)
    assert model.status == "training" and model.num_files == 1 and model.bucket == "fitset-phase-models"
    assert run(phase_repo.phase_model_versions, "ios", "PUSHUP") == ["v1.0"]
    run(phase_repo.finish_phase_model, model.id, keys={"pt_key": "k.pt", "onnx_key": "k.onnx", "mlpackage_key": "k.zip", "meta_key": "m"},
                                  metrics={"final": {"macro_f1": 0.8}}, mlflow_run_id="run1")
    done = run(phase_repo.get_phase_model, "ios", model.id)
    assert done.status == "completed" and done.pt_key == "k.pt" and done.metrics["final"]["macro_f1"] == 0.8
    from sqlalchemy.orm import selectinload
    from app.phase.models import PhaseModel
    row = query(select(PhaseModel).options(selectinload(PhaseModel.files)).where(PhaseModel.id == model.id))[0]
    assert [f.filename for f in row.files] == ["PUSHUP_DEV1_0001.parquet"]
    run(phase_repo.fail_phase_model, model.id, "boom")
    assert run(phase_repo.get_phase_model, "ios", model.id).error == "boom"
    assert run(phase_repo.list_phase_models, "ios", "SQUAT") == [] and len(run(phase_repo.list_phase_models, "ios")) == 1


def test_exercises_seed_and_reference(fresh_db):
    import app.exercises.repository as ex_repo
    mapping = [
        {"index": 0, "class": "SQUAT", "slug": "bodyweight-squat", "name": "맨몸 스쿼트", "exerciseId": "u1"},
        {"index": 1, "class": "PUSHUP", "slug": "push-up", "name": "푸시업", "exerciseId": "u2"},
        {"index": 7, "class": "DEADLIFT", "slug": "deadlift", "name": "데드리프트", "exerciseId": "u3"},
    ]
    assert run(ex_repo.upsert_exercises, mapping) == {"added": 3, "updated": 0}
    mapping[1]["name"] = "푸쉬업"
    assert run(ex_repo.upsert_exercises, mapping) == {"added": 0, "updated": 3}
    rows = run(ex_repo.list_exercises)
    assert [r.index for r in rows] == [0, 1, 7]
    assert rows[1].name == "푸쉬업" and rows[1].phase_supported is True and rows[2].phase_supported is False
    assert rows[1].angle_joints == "sh,el,wr" and rows[1].down_is_decreasing is True and rows[2].angle_joints is None
    import app.exercises.repository as ex_repo2
    assert run(ex_repo2.phase_rule, "PUSHUP") == (("sh", "el", "wr"), True)
    assert run(ex_repo2.phase_rule, "DEADLIFT") is None
    assert run(ex_repo2.is_class_known, "DEADLIFT") and run(ex_repo2.is_class_known, "WALL_SIT") is False

    f1 = run(data_repo.reserve_admin_upload, "ios", "PUSHUP", "DEV1")[0]
    c1 = run(phase_repo.reserve_collect, "ios", "SQUAT", "DEV1")
    c2 = run(phase_repo.reserve_collect, "ios", "BENCH_PRESS", "DEV1")
    assert query(select(DatasetFile).where(DatasetFile.filename == f1))[0].exercise.slug == "push-up"
    assert query(select(CollectFile).where(CollectFile.filename == c1))[0].exercise.index == 0
    assert query(select(CollectFile).where(CollectFile.filename == c2))[0].exercise is None


def test_status_hybrids_work_on_objects_and_queries(fresh_db):
    from app.phase.models import PhaseModel
    a = run(phase_repo.reserve_collect, "ios", "PUSHUP", "DEV1")
    b = run(phase_repo.reserve_collect, "ios", "PUSHUP", "DEV1")
    run(phase_repo.confirm_collect, "ios", a, 1789790030.2, 10)
    run(phase_repo.confirm_collect, "ios", b, 1789790030.2, 10)
    run(phase_repo.mark_labeling, "ios", [b])
    entries = {e.filename: e for e in run(phase_repo.list_files, "ios")}
    assert entries[a].is_labelable and not entries[a].is_labeling
    assert entries[b].is_labeling and not entries[b].is_labelable
    assert [r.filename for r in query(select(CollectFile).where(CollectFile.is_labeling))] == [b]
    assert [r.filename for r in query(select(CollectFile).where(CollectFile.is_labelable))] == [a]

    m = run(phase_repo.create_phase_model, "ios", "PUSHUP", "v1.0", [], window=50, stride=5, epochs=1)
    assert m.is_training and not m.is_completed
    run(phase_repo.finish_phase_model, m.id, keys={"pt_key": "k"}, metrics={}, mlflow_run_id="r")
    assert query(select(PhaseModel).where(PhaseModel.is_completed))[0].id == m.id
    assert query(select(PhaseModel).where(PhaseModel.is_training)) == []
