"""Лог бичих замын redaction (T-05, NFR-3).

`logging.Filter` нь бүх handler-ийн ӨМНӨ ажиллана — тиймээс форматлагдсан
мессеж, аргументууд хоёул шүүгдэнэ. Нэг ч handler тойрох зам байхгүй.
"""
from __future__ import annotations

import logging

from app.audit.redact import redact


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = redact(record.args)
            else:
                record.args = tuple(redact(a) for a in record.args)
        return True


def install(root: logging.Logger | None = None) -> RedactingFilter:
    """Root logger болон түүний handler-уудад шүүлтүүрийг суулгана."""
    logger = root or logging.getLogger()
    flt = RedactingFilter()
    logger.addFilter(flt)
    for handler in logger.handlers:
        handler.addFilter(flt)
    return flt
