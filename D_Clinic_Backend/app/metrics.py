"""In-process Prometheus counters for the live host (Step 9)."""

from __future__ import annotations

import math
import threading
from collections import deque
from time import perf_counter

_LOCK = threading.Lock()
_COUNTERS: dict[str, float] = {
    "followup_pii_refusals_total": 0,
    "followup_check_failures_total": 0,
    "followup_unsafe_intents_total": 0,
    "followup_summaries_total": 0,
    "followup_call_results_total": 0,
}
_LATENCIES: deque[float] = deque(maxlen=500)


def inc(name: str, amount: float = 1) -> None:
    with _LOCK:
        _COUNTERS[name] = _COUNTERS.get(name, 0) + amount


def observe_ms(ms: float) -> None:
    with _LOCK:
        _LATENCIES.append(float(ms))


def p95_ms() -> float:
    with _LOCK:
        if not _LATENCIES:
            return 0.0
        xs = sorted(_LATENCIES)
    if len(xs) == 1:
        return xs[0]
    idx = min(len(xs) - 1, max(0, math.ceil(0.95 * len(xs)) - 1))
    return xs[idx]


def snapshot() -> dict[str, float]:
    with _LOCK:
        out = dict(_COUNTERS)
    out["followup_latency_p95_ms"] = p95_ms()
    return out


class Timer:
    def __enter__(self):
        self._t0 = perf_counter()
        return self

    def __exit__(self, *exc):
        observe_ms((perf_counter() - self._t0) * 1000)


def render_prometheus(extra_lines: list[str] | None = None) -> str:
    snap = snapshot()
    lines = [
        "# HELP followup_pii_refusals_total De-id refusals (identity in a packet or field)",
        "# TYPE followup_pii_refusals_total counter",
        f"followup_pii_refusals_total {int(snap['followup_pii_refusals_total'])}",
        "# HELP followup_check_failures_total Summary / reckoner post-check failures (fallback used)",
        "# TYPE followup_check_failures_total counter",
        f"followup_check_failures_total {int(snap['followup_check_failures_total'])}",
        "# HELP followup_unsafe_intents_total SMS turns that created a medical staff task",
        "# TYPE followup_unsafe_intents_total counter",
        f"followup_unsafe_intents_total {int(snap['followup_unsafe_intents_total'])}",
        "# HELP followup_summaries_total Patient summaries generated",
        "# TYPE followup_summaries_total counter",
        f"followup_summaries_total {int(snap['followup_summaries_total'])}",
        "# HELP followup_call_results_total Call results recorded",
        "# TYPE followup_call_results_total counter",
        f"followup_call_results_total {int(snap['followup_call_results_total'])}",
        "# HELP followup_latency_p95_ms p95 latency of instrumented API calls (ms)",
        "# TYPE followup_latency_p95_ms gauge",
        f"followup_latency_p95_ms {snap['followup_latency_p95_ms']:.2f}",
    ]
    if extra_lines:
        lines.extend(extra_lines)
    return "\n".join(lines) + "\n"
