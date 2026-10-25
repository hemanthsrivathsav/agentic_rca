"""Agent runtime: step loop with checkpoints, breakpoints, resume and fork.

A *workflow* is an ordered list of :class:`Step`. Each step is a plain Python
function ``fn(ctx: StepContext) -> None`` that reads the shared state through
the context, calls models and tools through the context (so everything is
traced), and records claims.

The three building blocks everything else rests on:

1. the step loop saves a checkpoint (the full state as JSON) after every step;
2. every model, tool and retrieval call is recorded as a span;
3. :meth:`Runner.fork` restarts a run from any step with edited evidence.

Replay, breakpoints, approve/edit/reject and leave-one-out attribution are all
built from those three.
"""

from __future__ import annotations

import copy
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .knowledge import KnowledgeBase
from .llm import LLMClient
from .store import Store
from .tracing import Tracer
from .util import new_id, now_iso, rough_token_count


# --------------------------------------------------------------------------
# Workflow definition
# --------------------------------------------------------------------------

@dataclass
class Step:
    name: str                       # "retrieve_edd"
    label: str                      # "Retrieve EDD policy"
    agent: str                      # "Risk agent"
    fn: Callable[["StepContext"], None]
    irreversible: bool = False      # e.g. the step that approves an account


@dataclass
class Workflow:
    name: str
    steps: list[Step]

    def step(self, number: int) -> Step:
        return self.steps[number - 1]

    @property
    def size(self) -> int:
        return len(self.steps)


def initial_state(inputs: dict) -> dict:
    return {
        "inputs": inputs,
        "evidence": {},        # id -> evidence item that entered the context
        "claims": {},          # id -> claim made by an agent
        "messages": [],        # handoffs between agents
        "scratch": {},         # free-form working memory per agent
        "decision": None,
    }


# --------------------------------------------------------------------------
# Step context: the only way a step touches models, tools and knowledge
# --------------------------------------------------------------------------

class StepContext:
    def __init__(
        self,
        *,
        state: dict,
        step_no: int,
        step: Step,
        kb: KnowledgeBase,
        llm: LLMClient,
        tracer: Tracer,
        run: dict,
        exclude: set[str] | None = None,
        temperature: float = 0.0,
        sample: int = 0,
    ) -> None:
        self.state = state
        self.step_no = step_no
        self.step = step
        self.kb = kb
        self.llm = llm
        self.tracer = tracer
        self.run = run
        self.options = run.get("options", {})
        self.exclude = exclude or set()      # leave-one-out: hide these items
        self.temperature = temperature
        self.sample = sample
        self.events: list[dict] = []          # e.g. guard-mode blocks

    @property
    def agent(self) -> str:
        return self.step.agent

    # -- evidence ------------------------------------------------------
    def retrieve(self, query: str, *, top_k: int = 2, doc_ids: list[str] | None = None) -> list[dict]:
        swaps = self.options.get("swaps", {})
        guard_day = self.run["run_time"] if self.options.get("guard") else None
        with self.tracer.span(step=self.step_no, agent=self.agent, kind="retrieval", name="knowledge.search", input={"query": query, "top_k": top_k}) as sp:
            res = self.kb.retrieve(query, top_k=top_k, doc_ids=doc_ids, swaps=swaps, guard_day=guard_day)
            items = []
            for hit in res["chunks"]:
                chunk = self.kb.get(hit["id"])
                ev_id = f"ev:{chunk.id}"
                item = {
                    "id": ev_id,
                    "kind": "chunk",
                    "chunk_id": chunk.id,
                    "doc_id": chunk.doc_id,
                    "label": chunk.label,
                    "text": chunk.text,
                    "score": hit["score"],
                    "step": self.step_no,
                    "agent": self.agent,
                }
                self.state["evidence"][ev_id] = item
                if ev_id not in self.exclude:
                    items.append(item)
            sp.chunk_ids = [h["id"] for h in res["chunks"]]
            sp.output = {"chunks": sp.chunk_ids, "swapped": res["swapped"], "blocked": res["blocked"]}
            sp.simulated_seconds = 0.18
        for b in res["blocked"]:
            self.events.append({"kind": "blocked", "detail": {"step": self.step_no, **b}})
        return items

    def tool(self, tool_name: str, fn: Callable[..., Any], *, label: str, **args: Any) -> dict | None:
        """Call a tool; its result becomes an evidence item."""
        ev_id = f"ev:tool:{tool_name}"
        with self.tracer.span(step=self.step_no, agent=self.agent, kind="execute_tool", name=tool_name, input=args) as sp:
            result = fn(**args)
            sp.output = result
            sp.simulated_seconds = 0.35
        item = {"id": ev_id, "kind": "tool", "label": label, "text": json.dumps(result, ensure_ascii=False), "result": result, "step": self.step_no, "agent": self.agent}
        self.state["evidence"][ev_id] = item
        return None if ev_id in self.exclude else item

    def upstream_claims(self, claim_ids: list[str]) -> list[dict]:
        """Read claims handed over by another agent (respects leave-one-out)."""
        return [self.state["claims"][c] for c in claim_ids if c in self.state["claims"] and c not in self.exclude]

    # -- model ---------------------------------------------------------
    def chat(self, purpose: str, system: str, user: str) -> str:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        with self.tracer.span(step=self.step_no, agent=self.agent, kind="chat", name=purpose, input={"messages": messages}) as sp:
            resp = self.llm.complete(messages, purpose=purpose, temperature=self.temperature, sample=self.sample)
            sp.output = {"text": resp.text, "model": resp.model}
            sp.tokens_in, sp.tokens_out = resp.tokens_in, resp.tokens_out
            if resp.model.startswith("mock"):
                sp.simulated_seconds = round(0.6 + resp.tokens_out * 0.02 + resp.tokens_in * 0.002, 2)
        return resp.text

    # -- outputs -------------------------------------------------------
    def claim(self, claim_id: str, text: str, *, inputs: list[str], value: Any = None, kind: str = "claim") -> dict:
        """Record a claim. ``inputs`` = every evidence/claim id that was in the
        context for it. Which of them actually *drove* it is decided later by
        leave-one-out, not by the agent."""
        c = {"id": claim_id, "text": text, "agent": self.agent, "step": self.step_no, "inputs": inputs, "value": value, "kind": kind}
        self.state["claims"][claim_id] = c
        return c

    def handoff(self, to_agent: str, claim_ids: list[str]) -> None:
        self.state["messages"].append({"from": self.agent, "to": to_agent, "step": self.step_no, "claim_ids": claim_ids})

    def decide(self, value: str, text: str, *, inputs: list[str]) -> None:
        self.claim("decision", text, inputs=inputs, value=value, kind="decision")
        self.state["decision"] = {"value": value, "text": text}

    def note(self, key: str, value: Any) -> None:
        self.state["scratch"].setdefault(self.agent, {})[key] = value


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------

@dataclass
class Pause:
    rule: str
    step: int
    message: str
    detail: dict = field(default_factory=dict)


class Runner:
    def __init__(self, store: Store, kb: KnowledgeBase, llm: LLMClient, workflow: Workflow, rules: list | None = None) -> None:
        self.store = store
        self.kb = kb
        self.llm = llm
        self.workflow = workflow
        self.rules = rules or []

    # -- public API ----------------------------------------------------
    def start(self, *, subject: str, inputs: dict, run_time: str, options: dict | None = None, run_id: str | None = None, created_at: str | None = None) -> str:
        run_id = run_id or new_id("run")
        self.store.create_run({
            "id": run_id, "workflow": self.workflow.name, "subject": subject, "status": "running",
            "run_time": run_time, "parent_run_id": None, "forked_at": None, "fork_reason": None,
            "paused_at": None, "pause_reason": None, "options": options or {}, "created_at": created_at or now_iso(),
        })
        self.store.save_checkpoint(run_id, 0, initial_state(inputs))
        self._run_from(run_id, 1)
        return run_id

    def resume(self, run_id: str, action: str, *, swaps: dict[str, str] | None = None, note: str = "") -> str:
        """Act on a paused run. Returns the id of the run that continues.

        approve  continue the same run past the breakpoint
        reject   stop the run; nothing irreversible happens
        edit     fork from the paused step with edited evidence (``swaps``)
        """
        run = self._require(run_id)
        if run["status"] != "paused":
            raise ValueError(f"run {run_id} is {run['status']}, not paused")
        step = run["paused_at"]
        rule = next((r for r in self.rules if r.key == run["pause_reason"]), None)
        if action == "approve":
            opts = run["options"]
            opts.setdefault("ack", []).append(f"{run['pause_reason']}@{step}")
            self.store.update_run(run_id, status="running", options=opts, paused_at=None)
            self._event(run_id, step, "resumed", {"action": "approve", "note": note})
            # an "after" breakpoint paused once step N finished: carry on at N+1.
            # a "before" breakpoint paused ahead of step N: now run N itself.
            self._run_from(run_id, step if rule and rule.when == "before" else step + 1)
            return run_id
        if action == "reject":
            self.store.update_run(run_id, status="rejected")
            self._event(run_id, step, "rejected", {"note": note})
            return run_id
        if action == "edit":
            new = self.fork(run_id, from_step=step, swaps=swaps or {}, reason="edited at breakpoint")
            self.store.update_run(run_id, status="forked")
            return new
        raise ValueError(f"unknown action {action!r}")

    def fork(self, run_id: str, *, from_step: int, swaps: dict[str, str] | None = None, options: dict | None = None, reason: str = "fork", run_new_id: str | None = None) -> str:
        """Re-run ``run_id`` from ``from_step`` with edited evidence.

        Steps before ``from_step`` are reused: their checkpoints and spans are
        copied (spans marked ``cached``) so the fork is a complete run.

        If the run already has a fork from the same step with the same options
        (same swaps, breakpoints, guard ...), that fork is returned instead of
        running an identical copy.
        """
        parent = self._require(run_id)
        if not 1 <= from_step <= self.workflow.size:
            raise ValueError("from_step out of range")
        opts = copy.deepcopy(parent["options"])
        opts.pop("ack", None)
        opts["swaps"] = {**opts.get("swaps", {}), **(swaps or {})}
        opts.update(options or {})
        same = next((c for c in self.store.children(run_id) if c["forked_at"] == from_step and c["options"] == opts), None)
        if same and not run_new_id:
            return same["id"]
        new_id_ = run_new_id or new_id("run")
        self.store.create_run({
            "id": new_id_, "workflow": parent["workflow"], "subject": parent["subject"], "status": "running",
            "run_time": parent["run_time"], "parent_run_id": run_id, "forked_at": from_step, "fork_reason": reason,
            "paused_at": None, "pause_reason": None, "options": opts, "created_at": now_iso(),
        })
        for step, state in self.store.checkpoints(run_id):
            if step < from_step:
                self.store.save_checkpoint(new_id_, step, state)
        for sp in self.store.spans(run_id):
            if sp["step"] < from_step:
                sp = dict(sp, id=new_id("span"), run_id=new_id_, cached=1)
                self.store.add_span(sp)
        self._event(run_id, from_step, "forked", {"child": new_id_, "swaps": swaps or {}, "reason": reason})
        self._run_from(new_id_, from_step)
        return new_id_

    def rerun_step(self, run: dict, step_no: int, *, exclude: set[str] | None = None, temperature: float = 0.0, sample: int = 0, state: dict | None = None) -> dict:
        """Sandboxed re-execution of one step (nothing is stored).

        Used by leave-one-out attribution and decision-stability sampling.
        Returns the state after the step.
        """
        before = copy.deepcopy(state if state is not None else self.store.checkpoint(run["id"], step_no - 1))
        step = self.workflow.step(step_no)
        ctx = StepContext(state=before, step_no=step_no, step=step, kb=self.kb, llm=self.llm,
                          tracer=Tracer(None, run["id"]), run=run, exclude=exclude, temperature=temperature, sample=sample)
        step.fn(ctx)
        return ctx.state

    # -- internals -----------------------------------------------------
    def _require(self, run_id: str) -> dict:
        run = self.store.get_run(run_id)
        if not run:
            raise KeyError(run_id)
        return run

    def _event(self, run_id: str, step: int | None, kind: str, detail: dict) -> None:
        self.store.add_event({"id": new_id("evt"), "run_id": run_id, "step": step, "kind": kind, "detail": detail, "at": now_iso()})

    def _run_from(self, run_id: str, start: int) -> None:
        tracer = Tracer(self.store, run_id)
        tracer.model_calls = sum(1 for s in self.store.spans(run_id) if s["kind"] == "chat")
        for step_no in range(start, self.workflow.size + 1):
            run = self._require(run_id)
            step = self.workflow.step(step_no)
            state = copy.deepcopy(self.store.checkpoint(run_id, step_no - 1))

            # rules that look at the step about to run (e.g. irreversible action)
            pause = self._check(run, "before", step_no, state, state, tracer)
            if pause:
                self._pause(run_id, pause)
                return

            ctx = StepContext(state=state, step_no=step_no, step=step, kb=self.kb, llm=self.llm, tracer=tracer, run=run)
            t0 = max(time.time(), tracer._clock)
            with tracer.span(step=step_no, agent=step.agent, kind="invoke_agent", name=step.name, input={"label": step.label}) as sp:
                step.fn(ctx)
                sp.output = {"claims": [c for c, v in ctx.state["claims"].items() if v["step"] == step_no]}
                # the agent span lasts as long as the calls inside it
                sp.simulated_seconds = max(0.0, tracer._clock - t0)
            self.store.save_checkpoint(run_id, step_no, ctx.state)
            for ev in ctx.events:
                self._event(run_id, step_no, ev["kind"], ev["detail"])

            # rules that look at what the step just did (e.g. stale evidence entered)
            prev = self.store.checkpoint(run_id, step_no - 1)
            pause = self._check(run, "after", step_no, prev, ctx.state, tracer)
            if pause:
                self._pause(run_id, pause)
                return
        self.store.update_run(run_id, status="completed", paused_at=None)

    def _check(self, run: dict, when: str, step_no: int, before: dict, after: dict, tracer: Tracer) -> Pause | None:
        if not run["options"].get("breakpoints", True):
            return None
        acked = set(run["options"].get("ack", []))
        for rule in self.rules:
            if rule.when != when or not run["options"].get("rules", {}).get(rule.key, rule.default_on):
                continue
            if f"{rule.key}@{step_no}" in acked:
                continue
            hit = rule.check(run=run, step_no=step_no, step=self.workflow.step(step_no), before=before, after=after, kb=self.kb, store=self.store, tracer=tracer)
            if hit:
                return hit
        return None

    def _pause(self, run_id: str, pause: Pause) -> None:
        self.store.update_run(run_id, status="paused", paused_at=pause.step, pause_reason=pause.rule)
        self._event(run_id, pause.step, "breakpoint", {"rule": pause.rule, "message": pause.message, **pause.detail})


def estimate_tokens(text: str) -> int:
    return rough_token_count(text)
