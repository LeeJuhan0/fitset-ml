# ─────────────────────────────────────────────────────────────────────────────
# training 도메인 규칙 — I/O 없는 순수 함수/상수만 둔다.
# 버전 채번 규칙, 학습 상태 표기 규칙, best run 선정 규칙이 이 도메인의 불변식이다.
# ─────────────────────────────────────────────────────────────────────────────

# MLflow run 상태 → 앱 표기 규칙
STATUS_MAP = {"RUNNING": "running", "FINISHED": "completed", "FAILED": "failed"}


def version_key(version: str) -> tuple[int, int]:
    """버전 비교 규칙: v{major}.{minor}를 숫자쌍으로 본다.

    문자열 정렬은 "v1.10" < "v1.2" < "v1.9" 라서 최신 버전을 못 고른다.
    """
    major, minor = version[1:].split(".")
    return int(major), int(minor)


def bump_version(versions: list[str]) -> str:
    """버전 채번 규칙: 최신 버전의 minor +1, 없으면 v1.0.

    versions는 v{major}.{minor} 문자열 목록. 정렬 여부와 무관하게 숫자로 최신을 고른다.
    """
    if not versions:
        return "v1.0"           # 첫 버전
    major, minor = version_key(max(versions, key=version_key))   # "v1.10" → (1, 10)
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
