STATUS_MAP = {"RUNNING": "running", "FINISHED": "completed", "FAILED": "failed"}


def version_key(version: str) -> tuple[int, int]:
    """버전 비교 규칙: v{major}.{minor}를 숫자쌍으로 본다"""
    major, minor = version[1:].split(".")
    return int(major), int(minor)


def bump_version(versions: list[str]) -> str:
    """버전 채번 규칙: 최신 버전의 minor +1, 없으면 v1.0"""
    if not versions:
        return "v1.0"
    major, minor = version_key(max(versions, key=version_key))
    return f"v{major}.{minor + 1}"


def pick_best_run(runs: list) -> str | None:
    """best run 선정, FINISHED 중 val_accuracy 최고"""
    finished = [r for r in runs if r.status == "FINISHED" and r.metrics.val_accuracy is not None]
    if not finished:
        return None
    return max(finished, key=lambda r: r.metrics.val_accuracy).run_id
