"""Request-scoped context propagated without threading it through every signature.

Only ambient metadata belongs here — request ID and client IP, which the audit writer needs
but which no domain function should have to accept as a parameter. The tenant is
deliberately *not* here: it travels in the `Principal` and in the database session's
transaction-local GUC, so there is no ambient tenant a function could accidentally read
instead of the one it was given.
"""

from __future__ import annotations

from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("careos_request_id", default=None)
source_ip_var: ContextVar[str | None] = ContextVar("careos_source_ip", default=None)


def current_request_id() -> str | None:
    return request_id_var.get()


def current_source_ip() -> str | None:
    return source_ip_var.get()
