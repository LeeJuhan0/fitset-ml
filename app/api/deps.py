from fastapi import Path, HTTPException
from app.core.config import PLATFORMS


def validate_platform(platform: str = Path(...)) -> str:
    if platform not in PLATFORMS:
        raise HTTPException(status_code=400, detail="platform must be 'ios' or 'android'")
    return platform
