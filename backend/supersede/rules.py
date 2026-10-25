"""Breakpoint rules.

A rule is checked between steps. ``when="after"`` rules look at what a step
just did; ``when="before"`` rules look at the step about to run. A rule that
fires returns a :class:`~supersede.runtime.Pause`, and the runner stops the
run, keeps its checkpoint, and waits for approve / edit / reject.

Rules are deliberately meaning-based ("a replaced policy entered the
context") rather than position-based ("stop at node 3").
"""

from __future__ import annotations

import json

from .runtime import Pause
from .util import parse_day, similarity


def _fmt(value):
    d = parse_day(value)
    return f"{d.day} {d.strftime('%b %Y')}" if d else ""


class Rule:
    key = ""
    label = ""
    when = "after"
    default_on = True

    def check(self, **kw) -> Pause | None:  # pragma: no cover - interface
        raise NotImplementedError

    def describe(self) -> dict:
        return {"key": self.key, "label": self.label, "when": self.when, "default_on": self.default_on}


class StaleEvidenceRule(Rule):
    key = "stale_evidence"
    label = "A replaced source enters the context"

    def check(self, *, run, step_no, step, before, after, kb, **_):
        new_ids = [k for k in after["evidence"] if k not in before["evidence"]]
        for ev_id in new_ids:
            ev = after["evidence"][ev_id]
            if ev["kind"] != "chunk":
                continue
            if kb.status_on(ev["chunk_id"], run["run_time"]) == "retired":
                chunk = kb.get(ev["chunk_id"])
                current = kb.current_version(chunk.id, run["run_time"])
                return Pause(
                    rule=self.key,
                    step=step_no,
                    message=f"The {step.agent} retrieved {chunk.label}, which was replaced on {_fmt(chunk.retired_on)}.",
                    detail={"chunk_id": chunk.id, "current_id": current, "retired_on": chunk.retired_on,
                            "days_out_of_date": kb.days_out_of_date(chunk.id, run["run_time"]),
                            "suggested_swaps": {chunk.id: current}},
                )
        return None


class ToolLoopRule(Rule):
    key = "tool_loop"
    label = "The same tool runs 3 or more times"
    threshold = 3

    def check(self, *, run, step_no, store, **_):
        calls = [s for s in store.spans(run["id"]) if s["kind"] == "execute_tool"]
        for i, s in enumerate(calls):
            same = [c for c in calls if c["name"] == s["name"]
                    and similarity(json.dumps(c["input"], sort_keys=True), json.dumps(s["input"], sort_keys=True)) >= 0.9]
            if len(same) >= self.threshold:
                return Pause(rule=self.key, step=step_no,
                             message=f"Tool {s['name']} ran {len(same)} times with near-identical arguments.",
                             detail={"tool": s["name"], "count": len(same)})
        return None


class UngroundedBeforeActionRule(Rule):
    key = "ungrounded_before_action"
    label = "An unsupported claim precedes an account decision"
    when = "before"

    def check(self, *, step_no, step, before, **_):
        if not step.irreversible:
            return None
        ungrounded = [c for c in before["claims"].values() if c["kind"] == "claim" and not c["inputs"]]
        if ungrounded:
            ids = [c["id"] for c in ungrounded]
            names = ", ".join(f"claim {int(i[1:]):02d}" if i[1:].isdigit() else i for i in ids)
            verb = "has" if len(ids) == 1 else "have"
            return Pause(rule=self.key, step=step_no,
                         message=f"{names[0].upper() + names[1:]} {verb} no source in the agent's context, and the next step ({step.label.lower()}) cannot be undone.",
                         detail={"claim_ids": ids})
        return None


class BudgetRule(Rule):
    key = "budget"
    label = "The run passes 40 model calls"
    default_on = False
    limit = 40

    def check(self, *, run, step_no, tracer, **_):
        limit = run["options"].get("model_call_limit", self.limit)
        if tracer.model_calls > limit:
            return Pause(rule=self.key, step=step_no, message=f"{tracer.model_calls} model calls, over the limit of {limit}.",
                         detail={"model_calls": tracer.model_calls, "limit": limit})
        return None


def default_rules() -> list[Rule]:
    return [StaleEvidenceRule(), ToolLoopRule(), UngroundedBeforeActionRule(), BudgetRule()]
