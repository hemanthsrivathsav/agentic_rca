"""Application service: the one object the API talks to.

It wires the store, knowledge base, model client, workflow, rules and
analyzer together, seeds the synthetic demo, and exposes the operations the
UI needs (list runs, report, state at a step, resume, fork, replay, feedback).
"""

from __future__ import annotations

import os

from .llm import AzureOpenAIClient
from .provenance import Analyzer, fmt_day, state_diff
from .rules import default_rules
from .runtime import Runner
from .store import SQLiteStore, Store
from .util import new_id, now_iso
from .demo import kyc


class Supersede:
    def __init__(self, store: Store | None = None, *, llm: str | None = None, samples: int = 10) -> None:
        self.store = store or SQLiteStore(os.environ.get("SUPERSEDE_DB", "supersede.db"))
        self.kb = kyc.knowledge()
        mode = (llm or os.environ.get("SUPERSEDE_LLM", "mock")).lower()
        self.llm = AzureOpenAIClient() if mode == "azure" else kyc.mock_llm()
        self.llm_mode = mode
        self.rules = default_rules()
        self.runner = Runner(self.store, self.kb, self.llm, kyc.workflow(), self.rules)
        self.analyzer = Analyzer(self.runner)
        self.samples = samples

    # -- demo data -----------------------------------------------------
    def reset_demo(self) -> None:
        self.store.clear()
        self.seed_demo()

    def seed_demo(self) -> None:
        if self.store.list_runs():
            return
        for c in kyc.customers():
            self.runner.start(subject=c["name"], inputs=kyc.customer_inputs(c), run_time=c["run_time"],
                              options=c.get("options", {}), run_id=c["run_id"], created_at=c["created_at"])

    def start_run(self, *, customer_id: str | None = None, inputs: dict | None = None, run_time: str = "2026-10-15", options: dict | None = None) -> dict:
        """Start a new run, either from a demo customer or from raw inputs."""
        if customer_id:
            c = next(c for c in kyc.customers() if c["run_id"] == customer_id)
            inputs, subject, run_time = kyc.customer_inputs(c), c["name"], c["run_time"]
        else:
            subject = inputs["name"]
        run_id = self.runner.start(subject=subject, inputs=inputs, run_time=run_time, options=options or {"breakpoints": True}, run_id=new_id("KYC"))
        return self.report(run_id)

    # -- reading -------------------------------------------------------
    def report(self, run_id: str, *, refresh: bool = False) -> dict:
        run = self.store.get_run(run_id)
        if not run:
            raise KeyError(run_id)
        cached = None if refresh else self.store.analysis(run_id)
        if cached and cached["run"]["status"] == run["status"] and cached["run"]["paused_at"] == run["paused_at"]:
            rep = cached
        else:
            rep = self.analyzer.analyze(run_id, samples=self.samples)
        rep = dict(rep)
        rep["run"] = run
        rep["events"] = self.store.events(run_id)
        rep["feedback"] = self.store.feedback(run_id)
        rep["forks"] = [self._brief(c) for c in self.store.children(run_id)]
        rep["parent"] = self._brief(self.store.get_run(run["parent_run_id"])) if run["parent_run_id"] else None
        rep["rules"] = [dict(r.describe(), on=run["options"].get("rules", {}).get(r.key, r.default_on)) for r in self.rules]
        return rep

    def _brief(self, run: dict | None) -> dict | None:
        if not run:
            return None
        return {"id": run["id"], "status": run["status"], "forked_at": run["forked_at"], "fork_reason": run["fork_reason"],
                "swaps": run["options"].get("swaps", {}), "created_at": run["created_at"]}

    def summary(self, run_id: str) -> dict:
        rep = self.report(run_id)
        run = rep["run"]
        return {
            "id": run["id"], "workflow": run["workflow"], "subject": run["subject"], "status": run["status"],
            "run_time": run["run_time"], "created_at": run["created_at"], "paused_at": run["paused_at"],
            "decision": (rep.get("decision") or {}).get("value"), "finding": rep["finding"], "finding_label": rep["finding_label"],
            "counts": rep["counts"], "days_out_of_date": rep["days_out_of_date"],
            "replay_decision": (rep.get("replay") or {}).get("decision_after"),
            "stability": rep.get("stability"), "forks": len(rep["forks"]),
        }

    def list_runs(self, *, include_forks: bool = False) -> list[dict]:
        runs = self.store.list_runs()
        return [self.summary(r["id"]) for r in runs if include_forks or not r["parent_run_id"]]

    def overview(self) -> dict:
        runs = self.list_runs()
        bad = [r for r in runs if r["finding"] in ("confirmed_by_replay", "decision_used_replaced")]
        used_old = [r for r in runs if r["counts"]["replaced"] > 0]
        # rank by exposure: a wrong decision already taken, then a decision waiting
        # at a breakpoint, then claims built on replaced sources
        def exposure(r: dict) -> int:
            if r["finding"] == "confirmed_by_replay":
                return 5
            if r["status"] == "paused":
                return 4
            return {"decision_used_replaced": 3, "claim_used_replaced": 2, "outcome_unchanged": 1}.get(r["finding"], 0)
        ranked = sorted([r for r in runs if exposure(r)], key=lambda r: (-exposure(r), r["created_at"]))
        # recently replaced sources and how many top-level runs still used them
        replaced = []
        for old_id, new_id_ in self.kb.replaced_by.items():
            old, new = self.kb.get(old_id), self.kb.get(new_id_)
            users = [r["id"] for r in runs if any(e.get("chunk_id") == old_id for e in self.report(r["id"])["evidence"].values())]
            replaced.append({"old": old.label, "new": new.label, "on": new.effective_on, "on_label": fmt_day(new.effective_on),
                             "kind": old.kind, "runs_using_old": users})
        return {
            "totals": {
                "runs": len(runs),
                "paused": sum(1 for r in runs if r["status"] == "paused"),
                "used_replaced": len(used_old),
                "decision_affected": len(bad),
                "unsourced_claims": sum(r["counts"]["nosource"] for r in runs),
                "runs_with_unsourced": sum(1 for r in runs if r["counts"]["nosource"]),
            },
            "ranked": ranked[:5],
            "replaced": sorted(replaced, key=lambda x: x["on"], reverse=True),
            "llm": self.llm_mode,
        }

    def state(self, run_id: str, step: int) -> dict:
        after = self.store.checkpoint(run_id, step)
        if after is None:
            raise KeyError(f"no checkpoint for step {step}")
        before = self.store.checkpoint(run_id, step - 1) if step > 0 else None
        spans = [s for s in self.store.spans(run_id) if s["step"] == step]
        return {"run_id": run_id, "step": step, "state": after, "diff": state_diff(before, after), "spans": spans}

    # -- acting --------------------------------------------------------
    def resume(self, run_id: str, action: str, *, swaps: dict | None = None, note: str = "") -> dict:
        run = self.store.get_run(run_id)
        if action == "edit" and not swaps:
            bp = next((e for e in reversed(self.store.events(run_id)) if e["kind"] == "breakpoint"), None)
            swaps = (bp or {}).get("detail", {}).get("suggested_swaps", {})
        new_run = self.runner.resume(run_id, action, swaps=swaps, note=note)
        return self.report(new_run, refresh=True)

    def fork(self, run_id: str, *, from_step: int, swaps: dict | None = None, guard: bool | None = None, reason: str = "manual fork") -> dict:
        opts = {"breakpoints": False}
        if guard is not None:
            opts["guard"] = guard
        new_run = self.runner.fork(run_id, from_step=from_step, swaps=swaps or {}, options=opts, reason=reason)
        return self.report(new_run, refresh=True)

    def set_rule(self, run_id: str, key: str, on: bool) -> dict:
        run = self.store.get_run(run_id)
        opts = run["options"]
        opts.setdefault("rules", {})[key] = on
        self.store.update_run(run_id, options=opts)
        return self.report(run_id)

    def add_feedback(self, run_id: str, verdict: str, note: str = "", author: str = "reviewer") -> dict:
        if verdict not in ("correct", "wrong", "needs_review"):
            raise ValueError("verdict must be correct, wrong or needs_review")
        self.store.add_feedback({"id": new_id("fb"), "run_id": run_id, "verdict": verdict, "note": note, "author": author, "at": now_iso()})
        return {"run_id": run_id, "feedback": self.store.feedback(run_id)}
