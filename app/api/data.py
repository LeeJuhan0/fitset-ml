from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import validate_platform
from app.core.config import CLASSES
from app.core.s3 import generate_presigned_upload_url, get_index, put_index

router = APIRouter()


@router.get("/api/v1/{platform}/data")
def list_data(platform: str = Depends(validate_platform)):
    index = get_index(platform)
    return {
        "success": True,
        "code": "200",
        "message": "파일 목록을 조회했습니다.",
        "data": index,
    }


@router.get("/api/v1/{platform}/data/presigned-url")
def presigned_url(
    filename: str = Query(...),
    class_name: str = Query(..., alias="class"),
    platform: str = Depends(validate_platform),
):
    if class_name not in CLASSES:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 종목: {class_name}. 허용: {CLASSES}")

    url = generate_presigned_upload_url(platform, class_name, filename)
    s3_key = f"{platform}/raw/{class_name}/{filename}"

    return {
        "success": True,
        "code": "200",
        "message": "presigned URL을 발급했습니다.",
        "data": {
            "presignedUrl": url,
            "expiresIn": 300,
            "s3Key": s3_key,
        },
    }


class UploadConfirmRequest(BaseModel):
    filename: str
    class_name: str


@router.post("/api/v1/{platform}/data/upload-confirm")
def upload_confirm(body: UploadConfirmRequest, platform: str = Depends(validate_platform)):
    if body.class_name not in CLASSES:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 종목: {body.class_name}")

    index = get_index(platform)
    existing = {f["filename"] for f in index["files"]}
    if body.filename not in existing:
        index["files"].append({
            "filename": body.filename,
            "class": body.class_name,
            "collectedAt": datetime.now(timezone.utc).isoformat(),
            "trainedInVersion": None,
        })
        put_index(platform, index)

    return {
        "success": True,
        "code": "200",
        "message": "파일 목록에 등록됐습니다.",
        "data": {"filename": body.filename, "class": body.class_name},
    }
