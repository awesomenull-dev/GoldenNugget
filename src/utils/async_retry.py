"""Shared async retry helper.

The device backup/restore code originally had several hand-rolled retry
loops with subtly different exception sets, retry counts and backoffs. This
module is the single place those semantics live so a fix/behaviour tweak
applies everywhere at once.

Callers pass a ``coro_factory`` (a zero-arg awaitable factory — not a
coroutine object — so each attempt gets a fresh call) plus tuning knobs.
"""
import asyncio
from typing import Awaitable, Callable, Optional


async def async_retry(
    coro_factory: Callable[[], Awaitable],
    attempts: int,
    *,
    retry_if: Callable[[Exception], bool] = lambda exc: True,
    fixed_delay: Optional[float] = None,
    exp_cap: float = 15,
    on_retry: Optional[Callable[[int, int, Exception, float], None]] = None,
    on_failure: Optional[Callable[[Exception], None]] = None,
) -> Awaitable:
    """Run ``coro_factory()`` up to ``attempts`` times.

    On an exception matching ``retry_if`` (default: any) before the last
    attempt, wait ``fixed_delay`` or ``min(2 ** attempt, exp_cap)`` seconds,
    call ``on_retry(attempt, attempts, exc, delay)`` and try again. If the
    exception is not retryable, or all attempts are exhausted, call
    ``on_failure(exc)`` (if given) and re-raise it.

    ``attempt`` is 1-based and matches the delay formula ``2 ** attempt`` so
    callers that previously used ``min(2 ** attempt, 15)`` see identical
    behaviour.
    """
    last_error: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            return await coro_factory()
        except Exception as e:  # noqa: BLE001 — retry predicates decide
            last_error = e
            if attempt >= attempts or not retry_if(e):
                if on_failure is not None:
                    on_failure(e)
                raise
            delay = fixed_delay if fixed_delay is not None else min(2 ** attempt, exp_cap)
            if on_retry is not None:
                on_retry(attempt, attempts, e, delay)
            await asyncio.sleep(delay)
    raise last_error  # pragma: no cover — unreachable, kept for typing
