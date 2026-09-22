from datetime import datetime, timezone

from pydantic.alias_generators import to_camel


def utcnow() -> datetime:
    """현재 시각, timezone-aware UTC"""
    return datetime.now(timezone.utc)


def wire_alias(name: str) -> str:
    """와이어 alias, camelCase, class 예약어 회피"""
    return "class" if name == "class_name" else to_camel(name)


def parse_iso(value: str | None) -> datetime:
    """ISO 문자열 파싱, aware UTC 변환, 빈 값은 현재 시각"""
    if not value:
        return utcnow()
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
