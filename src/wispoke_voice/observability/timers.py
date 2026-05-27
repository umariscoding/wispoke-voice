"""
Latency timers — used to record per-stage durations into call logs.

Usage:

    metrics = LatencyTimer()
    with metrics.span("tool.get_available_slots"):
        slots = await api_client.get_slots(...)

    # at session end:
    api_client.finalize_call_log(call_log_id, latency_metrics=metrics.snapshot())
"""

from __future__ import annotations

import contextlib
import time
from collections import defaultdict
from typing import Dict, Iterator, List


class LatencyTimer:
    """Aggregates per-span durations (ms). Thread-safe enough for asyncio."""

    __slots__ = ("_buckets",)

    def __init__(self) -> None:
        self._buckets: Dict[str, List[float]] = defaultdict(list)

    @contextlib.contextmanager
    def span(self, name: str) -> Iterator[None]:
        start = time.monotonic()
        try:
            yield
        finally:
            self._buckets[name].append((time.monotonic() - start) * 1000.0)

    def record(self, name: str, ms: float) -> None:
        self._buckets[name].append(ms)

    def snapshot(self) -> Dict[str, Dict[str, float]]:
        """Return p50/p95/mean/count per span name. Empty buckets are omitted."""
        out: Dict[str, Dict[str, float]] = {}
        for name, samples in self._buckets.items():
            if not samples:
                continue
            ordered = sorted(samples)
            n = len(ordered)
            out[name] = {
                "count": float(n),
                "mean": sum(ordered) / n,
                "p50": ordered[max(0, int(n * 0.50) - 1)],
                "p95": ordered[max(0, int(n * 0.95) - 1)],
                "max": ordered[-1],
            }
        return out
