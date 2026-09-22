"""exercises 순수 규칙, 검증된 종목별 각도 규칙과 파싱"""
PHASE_RULES = {
    "PUSHUP": ("sh,el,wr", True),
    "SQUAT": ("hip,kn,an", True),
    "DUMBBELL_CURL": ("sh,el,wr", False),
}


def parse_rule(angle_joints: str | None, down_is_decreasing: bool | None) -> tuple[tuple[str, ...], bool] | None:
    """마스터 열 → (관절 3개, 내려감 방향), 없으면 None"""
    if not angle_joints or down_is_decreasing is None:
        return None
    joints = tuple(j.strip() for j in angle_joints.split(","))
    if len(joints) != 3:
        return None
    return joints, down_is_decreasing


def class_folder(index: int, class_name: str) -> str:
    """버킷 폴더명, 인덱스 순서 정렬, 예 001_PUSHUP"""
    return f"{index:03d}_{class_name}"
