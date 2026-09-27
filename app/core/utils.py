import signal
from datetime import datetime, timezone

from pydantic.alias_generators import to_camel

LOST_PROCESS_ERROR = "학습 프로세스가 사라짐, 서버 재시작이나 배포로 중단"


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


def exit_error(returncode: int, log_tail: str) -> str:
    """종료 코드와 로그 끝부분으로 실패 사유, SIGKILL 은 메모리 부족 추정"""
    if returncode == -signal.SIGKILL:
        head = "학습 프로세스가 SIGKILL 로 종료, 메모리 부족(OOM) 추정"
    elif returncode < 0:
        head = f"학습 프로세스가 시그널 {signal.Signals(-returncode).name} 로 종료"
    else:
        head = f"학습 프로세스가 종료 코드 {returncode} 로 실패"
    tail = log_tail.strip()
    return f"{head}\n{tail}" if tail else head


def read_tail(path, limit: int = 2000) -> str:
    """로그 파일 끝부분, 없으면 빈 문자열"""
    try:
        return path.read_text(errors="replace")[-limit:]
    except OSError:
        return ""
