from __future__ import annotations

import logging
from collections import deque

_buf: deque[str] = deque(maxlen=50)


class RingHandler(logging.Handler):
    """آخرین خطاها را برای پنل مالک نگه می‌دارد."""

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno >= logging.WARNING:
            _buf.append(f"{self.format(record)}")


def recent_errors(n: int = 10) -> list[str]:
    return list(_buf)[-n:]
