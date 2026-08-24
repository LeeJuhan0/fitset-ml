# ─────────────────────────────────────────────────────────────────────────────
# data 도메인 Service — 유스케이스 조율. repository(저장소)와 domain(규칙)을 조립한다.
# HTTP를 모른다(형식 검증·상태코드는 router 담당).
# ─────────────────────────────────────────────────────────────────────────────
import io

import pandas as pd

from app.data.repository import (   # 이름으로 import — 테스트가 이 네임스페이스를 monkeypatch 한다
    download_csv_bytes,
    generate_presigned_user_upload_url,
    get_index,
    get_uploads_index,
    mark_user_uploaded,
    reserve_user_upload,
    upload_csv_key,
)

UPLOAD_STATUSES = {"pending", "approved", "rejected"}   # 대장 상태 전이: pending → approved | rejected

PRESIGNED_EXPIRES_SECONDS = 300   # 업로드 URL 유효시간
STATS_TRIM_SECONDS = 3.0          # 통계 계산 시 앞뒤로 잘라내는 구간(기기 조작 노이즈 제거)
SENSOR_CHANNELS = ["ax", "ay", "az", "gx", "gy", "gz"]


def list_data(platform: str) -> dict:
    # 등록된 파일 목록 전체 — {platform, files:[...]} 그대로 반환
    return get_index(platform)


def issue_upload_url(platform: str, class_name: str, user_id: str, device_id: str) -> dict:
    """파일명 채번·예약 → presigned PUT URL 발급까지의 업로드 1단계 유스케이스.

    유저 자동수집 경로 — 격리 버킷(user_uploads)의 {platform}/{userId}/ 아래로만 발급한다.
    """
    filename = reserve_user_upload(platform, class_name, user_id, device_id)   # 예약(uploaded=False, pending)
    url = generate_presigned_user_upload_url(platform, user_id, filename)      # 서명 URL
    return {
        "presignedUrl": url,                                 # 앱이 이 URL로 CSV를 직접 PUT
        "expiresIn": PRESIGNED_EXPIRES_SECONDS,              # URL 유효시간(초)
        "s3Key": upload_csv_key(platform, user_id, filename),  # 업로드 경로(격리 버킷 내)
        "filename": filename,                                # 서버가 부여한 파일명(앱이 upload-confirm에 다시 보냄)
    }


def confirm_upload(platform: str, filename: str) -> bool:
    """S3 PUT 완료 후 업로드 대장의 예약 항목을 uploaded=True로 확정. 예약이 없으면 False."""
    return mark_user_uploaded(platform, filename)


def file_stats(platform: str, filename: str) -> dict | None:
    """센서 CSV의 채널별 mean/min/max/std 요약. 파일이 인덱스에 없으면 None.

    수집 시작·종료 직후는 기기를 집거나 내려놓는 동작이 섞이므로 앞뒤
    STATS_TRIM_SECONDS 초를 잘라내고 계산한다. 트림하면 남는 게 없을 만큼
    짧은 파일은 전체 구간으로 계산하고 trim_applied=False로 알린다.
    """
    index = get_index(platform)
    entry = next((f for f in index["files"] if f["filename"] == filename), None)
    if entry is None:
        return None

    raw = download_csv_bytes(platform, entry["class"], filename)
    df = pd.read_csv(io.BytesIO(raw))

    t = (df["timestamp"] - df["timestamp"].iloc[0]) / 1e9   # ns → 경과 초
    duration = float(t.iloc[-1])
    trimmed = df[(t >= STATS_TRIM_SECONDS) & (t <= duration - STATS_TRIM_SECONDS)]
    trim_applied = len(trimmed) > 0
    used = trimmed if trim_applied else df

    return {
        "filename": filename,
        "class": entry["class"],
        "trim_seconds": STATS_TRIM_SECONDS,
        "trim_applied": trim_applied,
        "duration_seconds": round(duration, 1),
        "total_rows": int(len(df)),
        "used_rows": int(len(used)),
        "channels": [
            {
                "channel": c,
                "mean": round(float(used[c].mean()), 4),
                "min": round(float(used[c].min()), 4),
                "max": round(float(used[c].max()), 4),
                "std": round(float(used[c].std()), 4),
            }
            for c in SENSOR_CHANNELS
        ],
    }


def list_uploads(platform: str, status: str | None = None) -> dict:
    """유저 업로드 대장 조회 — 어드민 승인 대기 패널용. status로 필터(None이면 전체)."""
    index = get_uploads_index(platform)
    uploads = index["uploads"]
    if status is not None:
        uploads = [u for u in uploads if u.get("status") == status]
    return {"platform": platform, "uploads": uploads}


def promote_upload(platform: str, filename: str) -> dict:
    """어드민 승인 승격 유스케이스 — 인터페이스만 확정, 처리 로직은 구현 예정.

    계획(07. 명세 §4.9):
      1) 대장에서 해당 filename이 uploaded=True·status=pending인지 확인
      2) 자동 검증 — CSV 스키마(timestamp+6채널), 최소 길이, 라벨 sanity
      3) user-uploads → dataset 버킷 CopyObject ({platform}/raw/{class}/{filename})
      4) 학습 인덱스(index.json)에 등록 (uploaded=True, userId 보존)
      5) 대장 status=approved 전이
    """
    raise NotImplementedError("승격 처리 로직은 구현 예정")


def reject_upload(platform: str, filename: str) -> dict:
    """어드민 반려 유스케이스 — 인터페이스만 확정, 처리 로직은 구현 예정.

    계획: 대장에서 pending 항목 확인 → status=rejected 전이 (객체 삭제 여부는 정책 미정).
    """
    raise NotImplementedError("반려 처리 로직은 구현 예정")
