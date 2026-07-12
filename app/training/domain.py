# ─────────────────────────────────────────────────────────────────────────────
# training 도메인 규칙 — I/O 없는 순수 함수/상수만 둔다.
# 버전 채번 규칙, 학습 상태 표기 규칙, best run 선정 규칙이 이 도메인의 불변식이다.
# ─────────────────────────────────────────────────────────────────────────────

# MLflow run 상태 → 앱 표기 규칙
STATUS_MAP = {"RUNNING": "running", "FINISHED": "completed", "FAILED": "failed"}


def bump_version(versions: list[str]) -> str:
    """버전 채번 규칙: 마지막 버전의 minor +1, 없으면 v1.0.

    versions는 오름차순 정렬된 v{major}.{minor} 문자열 목록.
    """
    if not versions:
        return "v1.0"           # 첫 버전
    major, minor = map(int, versions[-1][1:].split("."))   # "v1.3" → (1, 3)
    return f"v{major}.{minor + 1}"   # minor +1


def pick_best_run(runs: list[dict]) -> str | None:
    """best run 선정 규칙: FINISHED이고 valAccuracy가 기록된 run 중 최고 정확도."""
    finished = [
        r for r in runs
        if r["status"] == "FINISHED" and r["metrics"]["valAccuracy"] is not None
    ]
    if not finished:
        return None
    return max(finished, key=lambda r: r["metrics"]["valAccuracy"])["runId"]
