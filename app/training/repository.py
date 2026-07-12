# ─────────────────────────────────────────────────────────────────────────────
# training 도메인 Repository — 모델 버전 목록 조회·다음 버전 채번.
# (인덱스 조회는 core.s3.get_index를 그대로 쓰고, MLflow 접근은 service가 클라이언트로 직접 한다)
# ─────────────────────────────────────────────────────────────────────────────
import re

from app.core import s3
from app.training import domain


def list_model_versions(platform: str) -> list[str]:
    # models_bucket의 {platform}/ 아래 "폴더(prefix)"들을 훑어 v×.× 버전만 추린다.
    paginator = s3._client().get_paginator("list_objects_v2")   # 페이지 단위 목록 조회기
    pages = paginator.paginate(
        Bucket=s3.settings.models_bucket,
        Prefix=f"{platform}/",
        Delimiter="/",          # "/"로 끊어 하위 폴더(CommonPrefixes)만 받기
    )
    versions = []
    for page in pages:
        for prefix in page.get("CommonPrefixes", []):        # 각 하위 폴더
            name = prefix["Prefix"].rstrip("/").split("/")[-1]   # 마지막 경로 조각(폴더명)
            if re.match(r"v\d+\.\d+", name):                 # v숫자.숫자 형태만
                versions.append(name)
    return sorted(versions)     # 오름차순(문자열 정렬)


def next_version(platform: str) -> str:
    # 다음 버전 채번 — 규칙(domain.bump_version)은 순수, 목록 조회만 I/O.
    return domain.bump_version(list_model_versions(platform))
