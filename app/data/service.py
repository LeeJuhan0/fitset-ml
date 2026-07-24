# ─────────────────────────────────────────────────────────────────────────────
# data 도메인 Service — 유스케이스 조율. repository(저장소)와 domain(규칙)을 조립한다.
# HTTP를 모른다(형식 검증·상태코드는 router 담당).
# ─────────────────────────────────────────────────────────────────────────────
import io

import pandas as pd

from app.data.repository import (   # 이름으로 import — 테스트가 이 네임스페이스를 monkeypatch 한다
    csv_key,
    download_csv_bytes,
    generate_presigned_upload_url,
    get_index,
    mark_uploaded,
    reserve_upload,
)

PRESIGNED_EXPIRES_SECONDS = 300   # 업로드 URL 유효시간
STATS_TRIM_SECONDS = 3.0          # 통계 계산 시 앞뒤로 잘라내는 구간(기기 조작 노이즈 제거)
SENSOR_CHANNELS = ["ax", "ay", "az", "gx", "gy", "gz"]


def list_data(platform: str) -> dict:
    # 등록된 파일 목록 전체 — {platform, files:[...]} 그대로 반환
    return get_index(platform)


def issue_upload_url(platform: str, class_name: str, device_id: str) -> dict:
    """파일명 채번·예약 → presigned PUT URL 발급까지의 업로드 1단계 유스케이스."""
    filename = reserve_upload(platform, class_name, device_id)             # 예약(uploaded=False)
    url = generate_presigned_upload_url(platform, class_name, filename)    # 서명 URL
    return {
        "presignedUrl": url,                              # 앱이 이 URL로 CSV를 직접 PUT
        "expiresIn": PRESIGNED_EXPIRES_SECONDS,           # URL 유효시간(초)
        "s3Key": csv_key(platform, class_name, filename), # 업로드 경로
        "filename": filename,                             # 서버가 부여한 파일명(앱이 upload-confirm에 다시 보냄)
    }


def confirm_upload(platform: str, filename: str) -> bool:
    """S3 PUT 완료 후 예약 항목을 uploaded=True로 확정. 예약이 없으면 False."""
    return mark_uploaded(platform, filename)


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
