"""Span recorder.

Every model call, tool call and retrieval inside a step is recorded as a span
with OpenTelemetry GenAI-style kinds (``invoke_agent``, ``chat``,
``retrieval``, ``execute_tool``), timing and token counts.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Iterator

from .store import Store
from .util import new_id


class SpanHandle:
    def __init__(self) -> None:
        self.output: Any = None
        self.chunk_ids: list[str] = []
        self.tokens_in = 0
        self.tokens_out = 0
        self.error: str | None = None
        # The mock model returns instantly; it reports a realistic duration here
        # so the cost-and-time view looks like a real run. None = measure.
        self.simulated_seconds: float | None = None


class Tracer:
    def __init__(self, store: Store | None, run_id: str) -> None:
        # store=None gives a silent tracer, used for sandboxed re-runs
        # (leave-one-out attribution, stability sampling).
        self.store = store
        self.run_id = run_id
        self.model_calls = 0
        self._clock = time.time()

    @contextmanager
    def span(self, *, step: int, agent: str, kind: str, name: str, input: Any = None) -> Iterator[SpanHandle]:
        handle = SpanHandle()
        started = time.perf_counter()
        wall = max(time.time(), self._clock)
        try:
            yield handle
        except Exception as exc:  # recorded, then re-raised
            handle.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            measured = time.perf_counter() - started
            elapsed = handle.simulated_seconds if handle.simulated_seconds is not None else measured
            self._clock = wall + elapsed
            if kind == "chat":
                self.model_calls += 1
            if self.store is not None:
                self._record(step, agent, kind, name, input, handle, wall, elapsed)

    def _record(self, step: int, agent: str, kind: str, name: str, input: Any, handle: SpanHandle, wall: float, elapsed: float) -> None:
        self.store.add_span({
            "id": new_id("span"),
            "run_id": self.run_id,
            "step": step,
            "agent": agent,
            "kind": kind,
            "name": name,
            "input": input,
            "output": handle.output,
            "chunk_ids": handle.chunk_ids,
            "tokens_in": handle.tokens_in,
            "tokens_out": handle.tokens_out,
            "started": wall,
            "ended": wall + elapsed,
            "error": handle.error,
            "cached": 0,
        })
