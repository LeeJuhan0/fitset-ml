import importlib

import numpy as np

NOSE = 0


class L:
    """왼쪽 관절 MediaPipe 인덱스, 워치 착용 쪽"""
    SHOULDER, ELBOW, WRIST, HIP, KNEE, ANKLE = 11, 13, 15, 23, 25, 27


class R:
    """오른쪽 관절 MediaPipe 인덱스"""
    SHOULDER, ELBOW, WRIST, HIP, KNEE, ANKLE = 12, 14, 16, 24, 26, 28


ARMS = (L.SHOULDER, L.ELBOW, L.WRIST, R.SHOULDER, R.ELBOW, R.WRIST)
LEGS = (L.HIP, L.KNEE, L.ANKLE, R.HIP, R.KNEE, R.ANKLE)
TORSO = (L.SHOULDER, R.SHOULDER, L.HIP, R.HIP)


def load_motion(class_name: str):
    """종목 판정 모듈, 없으면 None"""
    name = f"app.motions.{class_name.lower()}_util"
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as e:
        if e.name != name:
            raise
        return None


def joint_angle(p: np.ndarray, a: int, b: int, c: int) -> np.ndarray:
    """프레임별 b 꼭짓점 각도, 도 단위"""
    v1, v2 = p[:, a] - p[:, b], p[:, c] - p[:, b]
    cos = np.sum(v1 * v2, axis=1) / (np.linalg.norm(v1, axis=1) * np.linalg.norm(v2, axis=1) + 1e-9)
    return np.degrees(np.arccos(np.clip(cos, -1, 1)))


def both_elbows(p: np.ndarray) -> np.ndarray:
    """양 팔꿈치 각도 평균"""
    return (joint_angle(p, L.SHOULDER, L.ELBOW, L.WRIST) + joint_angle(p, R.SHOULDER, R.ELBOW, R.WRIST)) / 2


def both_knees(p: np.ndarray) -> np.ndarray:
    """양 무릎 각도 평균"""
    return (joint_angle(p, L.HIP, L.KNEE, L.ANKLE) + joint_angle(p, R.HIP, R.KNEE, R.ANKLE)) / 2


def arm_opening(p: np.ndarray) -> np.ndarray:
    """왼 위팔과 어깨선 각도, 팔 벌리면 증가"""
    return joint_angle(p, R.SHOULDER, L.SHOULDER, L.ELBOW)


def both_arm_opening(p: np.ndarray) -> np.ndarray:
    """양 위팔과 어깨선 각도 평균"""
    return (arm_opening(p) + joint_angle(p, L.SHOULDER, R.SHOULDER, R.ELBOW)) / 2


def torso_lean(p: np.ndarray) -> np.ndarray:
    """몸통과 수직선 각도, 숙이면 증가, y 아래 방향"""
    v = (p[:, L.SHOULDER] + p[:, R.SHOULDER]) / 2 - (p[:, L.HIP] + p[:, R.HIP]) / 2
    return np.degrees(np.arccos(np.clip(-v[:, 1] / (np.linalg.norm(v, axis=1) + 1e-9), -1, 1)))


def torso_twist(world: np.ndarray) -> np.ndarray:
    """어깨선과 골반선 회전각, 왼쪽 회전 양수"""
    up = (world[:, L.SHOULDER] + world[:, R.SHOULDER]) / 2 - (world[:, L.HIP] + world[:, R.HIP]) / 2
    up /= np.linalg.norm(up, axis=1, keepdims=True) + 1e-9
    s = world[:, R.SHOULDER] - world[:, L.SHOULDER]
    h = world[:, R.HIP] - world[:, L.HIP]
    s = s - np.sum(s * up, axis=1, keepdims=True) * up
    h = h - np.sum(h * up, axis=1, keepdims=True) * up
    return np.degrees(np.arctan2(np.sum(np.cross(h, s) * up, axis=1), np.sum(h * s, axis=1)))


def height(image: np.ndarray, joint: int) -> np.ndarray:
    """발목 기준 관절 높이, 키 대비 퍼센트"""
    ankle = (image[:, L.ANKLE, 1] + image[:, R.ANKLE, 1]) / 2
    body = np.nanmedian(ankle - image[:, NOSE, 1])
    return (ankle - image[:, joint, 1]) / body * 100
