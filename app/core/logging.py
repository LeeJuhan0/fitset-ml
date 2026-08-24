# ─────────────────────────────────────────────────────────────────────────────
# 로깅 설정과 traceId 자동 첨부 — ai-server core/logging.py 이식.
#
# ContextVar는 값을 담는 상자가 아니라 "열쇠"다 — 실제 값은 asyncio가 태스크마다
# 들고 다니는 숨은 딕셔너리(Context)에 저장되고, set/get은 지금 실행 중인 태스크의
# 딕셔너리에 이 열쇠로 쓰고 읽는다. 그래서 전역처럼 보여도 요청끼리 값이 안 섞인다.
#
# 흐름: trace_id_middleware(main.py)가 요청마다 trace_id_var.set() →
# 요청 처리 중의 모든 logger 호출에 _TraceIdFilter가 그 값을 붙임 →
# "2026-08-24 ... INFO fitset-ml [4a31f1fc...] POST /api/admin/v1/ios/train 202 84ms"
#
# 파일 저장 코드가 없는 건 의도 — stdout까지가 우리 책임(docker logs → CloudWatch),
# 수집·보관은 실행 환경 몫.
# ─────────────────────────────────────────────────────────────────────────────
import logging
from contextvars import ContextVar

# 요청 밖(부팅 로그, 학습 워커 등)의 문맥에서는 default "-"가 찍힌다
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")


class _TraceIdFilter(logging.Filter):
    # 모든 로그 레코드에 trace_id 속성을 붙인다 (레코드가 이미 갖고 있으면 존중)
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "trace_id"):
            record.trace_id = trace_id_var.get()
        return True


def configure_logging() -> None:
    """root 로거의 레벨과 포맷을 설정하고 traceId 필터를 부착한다.

    uvicorn 기본 액세스 로그는 끈다 — 같은 요청이 두 줄로 남는 것을 막고,
    소요 시간·traceId가 담긴 미들웨어 로그(main.py) 한 줄만 남긴다.
    uvicorn.error(부팅·종료·예외)는 그대로 둔다.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s [%(trace_id)s] %(message)s",
    )
    for handler in logging.getLogger().handlers:
        handler.addFilter(_TraceIdFilter())
    logging.getLogger("uvicorn.access").disabled = True
