"""Provenance analysis: why did the agents decide what they decided?

For a finished (or paused) run this module works out, claim by claim:

1. **Attribution.** Leave-one-out: re-run the claim's step with one input
   hidden. If the claim changes, that input *drove* it. Scores are each
   input's share of the total change.
2. **Validity.** Every driving document chunk is checked against its version
   record on the run date (current or retired, and for how many days).
3. **Status.** A claim is ``replaced`` if a retired chunk drove it, directly or
   through an upstream claim; ``nosource`` if nothing in context explains it;
   otherwise ``current``.
4. **Lineage.** The path from the decision back through driving inputs.
5. **Replay.** Fork the run with every retired chunk swapped for its current
   version, from the earliest step it entered, and diff the claims. A changed
   decision confirms the root cause.
6. **Stability.** Re-sample the decision step N times and count outcomes.

It also builds the node/edge graph and the per-step cost table the UI draws.
"""

from __future__ import annotations

from .runtime import Runner
from .util import now_iso, parse_day, similarity

DROVE_SHARE = 0.2     # an input "drove" a claim if it explains >= 20% of the change
MIN_CHANGE = 0.05     # ...and hiding it changed the claim by at least 5%
REPLAY_REASON = "replay with current versions"
REPORT_VERSION = 2    # bump when the report shape changes, so cached analyses are rebuilt

FINDINGS = {
    "healthy": "All evidence current",
    "unsourced": "Claim without a source",
    "retired_in_context": "Retired source retrieved, not used",
    "claim_used_replaced": "A claim used a replaced source",
    "decision_used_replaced": "Decision used replaced policy",
    "outcome_unchanged": "Replaced source used, outcome unchanged",
    "confirmed_by_replay": "Decision used replaced policy",
}


def fmt_day(value: str | None) -> str:
    d = parse_day(value)
    return f"{d.day} {d.strftime('%b %Y')}" if d else ""


# --------------------------------------------------------------------------
# State diff (for the state drawer)
# --------------------------------------------------------------------------

def state_diff(before: dict | None, after: dict) -> dict:
    """What changed in the agent's state during one step."""
    before = before or {"evidence": {}, "claims": {}, "messages": [], "scratch": {}, "decision": None}
    out: dict = {}
    for key in ("evidence", "claims"):
        added = [k for k in after[key] if k not in before[key]]
        changed = [k for k in after[key] if k in before[key] and after[key][k] != before[key][k]]
        removed = [k for k in before[key] if k not in after[key]]
        out[key] = {"added": added, "changed": changed, "removed": removed}
    out["messages"] = {"added": after["messages"][len(before["messages"]):]}
    out["scratch"] = {a: v for a, v in after["scratch"].items() if before["scratch"].get(a) != v}
    out["decision"] = after["decision"] if after["decision"] != before["decision"] else None
    return out


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------

class Analyzer:
    def __init__(self, runner: Runner) -> None:
        self.runner = runner
        self.store = runner.store
        self.kb = runner.kb
        self.wf = runner.workflow

    # -- attribution ---------------------------------------------------
    def _last_step(self, run: dict) -> int:
        """Latest step with a checkpoint (paused and rejected runs stop early)."""
        return max(s for s, _ in self.store.checkpoints(run["id"]))

    def attribute(self, run: dict, state: dict) -> dict[str, dict]:
        """Leave-one-out over every input of every claim."""
        result: dict[str, dict] = {}
        for cid, claim in state["claims"].items():
            raw: dict[str, float] = {}
            for inp in claim["inputs"]:
                raw[inp] = self._change(run, claim, {inp})
            total = sum(raw.values())
            # Redundant causes: if no single input matters but the claim has
            # several, two inputs may each be enough on their own. Remove pairs
            # and split the credit.
            if total == 0 and 2 <= len(claim["inputs"]) <= 6:
                ins = claim["inputs"]
                for i in range(len(ins)):
                    for j in range(i + 1, len(ins)):
                        ch = self._change(run, claim, {ins[i], ins[j]})
                        raw[ins[i]] += ch / 2
                        raw[ins[j]] += ch / 2
                raw = {k: round(v, 4) for k, v in raw.items()}
                total = sum(raw.values())
            shares = {k: (round(v / total, 3) if total > 0 else 0.0) for k, v in raw.items()}
            drove = [k for k in raw if shares[k] >= DROVE_SHARE and raw[k] >= MIN_CHANGE]
            result[cid] = {"change": raw, "share": shares, "drove": drove}
        return result

    def _change(self, run: dict, claim: dict, exclude: set[str]) -> float:
        """How much the claim changes when ``exclude`` is hidden (0..1)."""
        alt = self.runner.rerun_step(run, claim["step"], exclude=exclude)
        alt_claim = alt["claims"].get(claim["id"])
        if alt_claim is None:
            return 1.0
        if claim["kind"] == "decision" and alt_claim.get("value") != claim.get("value"):
            return 1.0
        return round(1.0 - similarity(claim["text"], alt_claim["text"]), 4)

    def supports(self, claim_text: str, evidence_text: str) -> bool:
        """Cheap corroboration check: enough shared content words.
        With a real model, replace with an entailment prompt."""
        stop = {"the", "a", "an", "of", "to", "and", "is", "on", "in", "for", "with", "this", "so", "no", "not", "are", "be"}
        cw = {w for w in claim_text.lower().replace(".", " ").split() if w not in stop and len(w) > 2}
        ew = set(evidence_text.lower().replace(".", " ").split())
        return len(cw & ew) >= 2

    # -- main entry ----------------------------------------------------
    def analyze(self, run_id: str, *, replay: bool = True, samples: int = 10) -> dict:
        run = self.store.get_run(run_id)
        if not run:
            raise KeyError(run_id)
        last = self._last_step(run)
        state = self.store.checkpoint(run_id, last)
        day = run["run_time"]

        # evidence validity
        evidence = {}
        for ev_id, ev in state["evidence"].items():
            item = dict(ev)
            if ev["kind"] == "chunk":
                status = self.kb.status_on(ev["chunk_id"], day)
                item["version_status"] = status
                item["days_out_of_date"] = self.kb.days_out_of_date(ev["chunk_id"], day)
                cur = self.kb.current_version(ev["chunk_id"], day)
                item["current_id"] = cur
                item["current_label"] = self.kb.get(cur).label
                item["retired_on"] = self.kb.get(ev["chunk_id"]).retired_on
            else:
                item["version_status"] = "current"
            evidence[ev_id] = item

        attr = self.attribute(run, state)

        # claim status, in step order
        claims = {}
        for cid, c in sorted(state["claims"].items(), key=lambda kv: (kv[1]["step"], kv[0])):
            a = attr[cid]
            via = []
            for inp in a["drove"]:
                if inp in evidence and evidence[inp]["version_status"] == "retired":
                    via.append(inp)
                elif inp in claims and claims[inp]["status"] == "replaced":
                    via.append(inp)
            if via:
                status = "replaced"
            elif c["kind"] == "claim" and (not c["inputs"] or not a["drove"]):
                status = "nosource"
            else:
                status = "current"
            main = max(a["share"], key=a["share"].get) if a["drove"] else None
            claims[cid] = {
                **c,
                "status": status,
                "replaced_via": via,
                "attribution": [
                    {"input": k, "share": a["share"][k], "change": a["change"][k], "drove": k in a["drove"],
                     "supports": self.supports(c["text"], evidence[k]["text"]) if k in evidence else None}
                    for k in c["inputs"]
                ],
                "main_source": main,
            }

        # lineage: everything that drove the decision, recursively
        path: list[str] = []
        if "decision" in claims:
            stack = ["decision"]
            while stack:
                n = stack.pop()
                if n in path:
                    continue
                path.append(n)
                if n in claims:
                    stack.extend(claims[n]["attribution"][i]["input"] for i in range(len(claims[n]["attribution"])) if claims[n]["attribution"][i]["drove"])

        retired = [e for e in evidence.values() if e.get("version_status") == "retired"]
        retired_driving = [e["id"] for e in retired if any(e["id"] in c["replaced_via"] for c in claims.values())]
        on_path = [e for e in retired_driving if e in path]

        # replay with current versions
        replay_info = None
        if replay and retired and run["status"] in ("completed", "paused", "forked"):
            replay_info = self._replay(run, state, retired, claims)

        if not retired:
            finding = "unsourced" if any(c["status"] == "nosource" for c in claims.values()) else "healthy"
        elif not retired_driving:
            finding = "retired_in_context"
        elif not on_path:
            finding = "claim_used_replaced"
        elif replay_info and replay_info["decision_changed"]:
            finding = "confirmed_by_replay"
        elif replay_info:
            finding = "outcome_unchanged"
        else:
            finding = "decision_used_replaced"

        first_wrong = None
        bad = [c for c in claims.values() if c["status"] == "replaced"]
        if bad:
            first = min(bad, key=lambda c: c["step"])
            entered = min(evidence[e]["step"] for e in first["replaced_via"] if e in evidence) if any(e in evidence for e in first["replaced_via"]) else first["step"]
            first_wrong = {"step": entered, "agent": self.wf.step(entered).agent, "label": self.wf.step(entered).label}

        report = {
            "version": REPORT_VERSION,
            "run": run,
            "analysed_at": now_iso(),
            "last_step": last,
            "decision": state.get("decision"),
            "finding": finding,
            "finding_label": FINDINGS[finding],
            "first_wrong_step": first_wrong,
            "days_out_of_date": max([e["days_out_of_date"] for e in retired if e["id"] in retired_driving] or [0]),
            "evidence": evidence,
            "claims": claims,
            "decision_path": path,
            "replay": replay_info,
            "stability": self.stability(run, samples) if "decision" in claims and samples else None,
            "steps": self.step_table(run_id),
            "counts": {
                "claims": sum(1 for c in claims.values() if c["kind"] == "claim"),
                "current": sum(1 for c in claims.values() if c["kind"] == "claim" and c["status"] == "current"),
                "replaced": sum(1 for c in claims.values() if c["kind"] == "claim" and c["status"] == "replaced"),
                "nosource": sum(1 for c in claims.values() if c["status"] == "nosource"),
                "evidence": len(evidence),
                "unused_evidence": sum(1 for e in evidence if not any(a["input"] == e and a["drove"] for c in claims.values() for a in c["attribution"])),
            },
        }
        report["graph"] = self.graph(report)
        report["read"] = self.analyst_read(report)
        self.store.save_analysis(run_id, report, report["analysed_at"])
        return report

    # -- replay --------------------------------------------------------
    def _replay(self, run: dict, state: dict, retired: list[dict], claims: dict) -> dict:
        swaps = {e["chunk_id"]: e["current_id"] for e in retired if e["current_id"] != e["chunk_id"]}
        if not swaps:
            return None
        from_step = min(e["step"] for e in retired)
        existing = [c for c in self.store.children(run["id"]) if c["fork_reason"] == REPLAY_REASON]
        if existing:
            child_id = existing[0]["id"]
        else:
            child_id = self.runner.fork(run["id"], from_step=from_step, swaps=swaps, options={"breakpoints": False}, reason=REPLAY_REASON)
        child = self.store.get_run(child_id)
        after = self.store.checkpoint(child_id, self.wf.size) or self.store.checkpoint(child_id, max(s for s, _ in self.store.checkpoints(child_id)))
        diff = []
        for cid, c in claims.items():
            new = after["claims"].get(cid)
            diff.append({"id": cid, "before": c["text"], "after": new["text"] if new else None,
                         "changed": bool(new) and similarity(c["text"], new["text"]) < 0.98})
        before_dec = (state.get("decision") or {}).get("value")
        after_dec = (after.get("decision") or {}).get("value")
        return {
            "run_id": child_id, "status": child["status"], "from_step": from_step, "swaps": swaps,
            "decision_before": before_dec, "decision_after": after_dec,
            "decision_changed": before_dec is not None and after_dec is not None and before_dec != after_dec,
            "claims": diff,
        }

    # -- stability -----------------------------------------------------
    def stability(self, run: dict, samples: int = 10) -> dict:
        step_no = self.store.checkpoint(run["id"], self._last_step(run))["claims"]["decision"]["step"]
        counts: dict[str, int] = {}
        for i in range(samples):
            out = self.runner.rerun_step(run, step_no, temperature=0.7, sample=i)
            v = (out.get("decision") or {}).get("value", "none")
            counts[v] = counts.get(v, 0) + 1
        top = max(counts.values())
        return {"samples": samples, "counts": counts, "stable": top == samples, "agreement": round(top / samples, 2)}

    # -- cost and time -------------------------------------------------
    def step_table(self, run_id: str) -> list[dict]:
        spans = self.store.spans(run_id)
        rows = []
        for i, step in enumerate(self.wf.steps, start=1):
            mine = [s for s in spans if s["step"] == i]
            agent_span = next((s for s in mine if s["kind"] == "invoke_agent"), None)
            rows.append({
                "step": i, "name": step.name, "label": step.label, "agent": step.agent, "irreversible": step.irreversible,
                "ran": agent_span is not None,
                "cached": bool(agent_span and agent_span["cached"]),
                "seconds": round(agent_span["ended"] - agent_span["started"], 2) if agent_span else 0,
                "tokens": sum(s["tokens_in"] + s["tokens_out"] for s in mine if s["kind"] == "chat"),
                "model_calls": sum(1 for s in mine if s["kind"] == "chat"),
                "tool_calls": sum(1 for s in mine if s["kind"] == "execute_tool"),
                "retrievals": sum(1 for s in mine if s["kind"] == "retrieval"),
            })
        return rows

    # -- graph for the UI ----------------------------------------------
    def graph(self, report: dict) -> dict:
        agents = []
        for s in self.wf.steps:
            if s.agent not in agents:
                agents.append(s.agent)
        columns = ["Evidence", *agents, "Outcome"]
        claims, evidence, path = report["claims"], report["evidence"], set(report["decision_path"])
        swaps = report["run"]["options"].get("swaps", {})
        nodes, edges = [], []

        # influence on the decision for sizing: max share along any driving edge
        weight: dict[str, float] = {}
        for c in claims.values():
            for a in c["attribution"]:
                weight[a["input"]] = max(weight.get(a["input"], 0.0), a["share"] if a["drove"] else 0.0)

        for ev in sorted(evidence.values(), key=lambda e: (e["step"], e["id"])):
            nodes.append({
                "id": ev["id"], "type": "evidence", "kind": ev["kind"], "label": ev["label"], "text": ev["text"],
                "column": 0, "step": ev["step"], "agent": ev["agent"],
                "status": ev.get("version_status", "current"), "weight": weight.get(ev["id"], 0.0),
                "on_path": ev["id"] in path, "retired_on": ev.get("retired_on"), "days_out_of_date": ev.get("days_out_of_date", 0),
                "swapped_in": ev.get("chunk_id") in swaps.values(),
            })
            if ev.get("version_status") == "retired" and ev.get("current_id"):
                cur = self.kb.get(ev["current_id"])
                rid = f"ev:{cur.id}"
                if rid not in evidence:
                    nodes.append({"id": rid, "type": "evidence", "kind": "chunk", "label": cur.label, "text": cur.text, "column": 0,
                                  "step": ev["step"], "agent": None, "status": "not_retrieved", "weight": 0.0, "on_path": False,
                                  "retired_on": None, "days_out_of_date": 0})
                edges.append({"from": rid, "to": ev["id"], "type": "replaces", "share": None, "on_path": False, "status": "replaces"})

        # A fork that swapped evidence keeps the version it swapped out, so a run
        # and its forks draw the same nodes and the UI can animate between them.
        for old, new in swaps.items():
            nid, oid = f"ev:{new}", f"ev:{old}"
            if nid not in evidence or oid in evidence or old not in self.kb.chunks:
                continue
            gone = self.kb.get(old)
            nodes.append({"id": oid, "type": "evidence", "kind": "chunk", "label": gone.label, "text": gone.text, "column": 0,
                          "step": evidence[nid]["step"], "agent": None, "status": "swapped_out", "weight": 0.0, "on_path": False,
                          "retired_on": gone.retired_on, "days_out_of_date": self.kb.days_out_of_date(old, report["run"]["run_time"])})
            edges.append({"from": nid, "to": oid, "type": "replaces", "share": None, "on_path": False, "status": "replaces"})

        for c in sorted(claims.values(), key=lambda c: (c["step"], c["id"])):
            col = len(columns) - 1 if c["kind"] == "decision" else 1 + agents.index(c["agent"])
            nodes.append({"id": c["id"], "type": c["kind"], "label": c["id"].upper() if c["kind"] == "claim" else "Decision",
                          "text": c["text"], "value": c.get("value"), "column": col, "step": c["step"], "agent": c["agent"],
                          "status": c["status"], "weight": weight.get(c["id"], 0.0), "on_path": c["id"] in path})
            for a in c["attribution"]:
                src_status = claims[a["input"]]["status"] if a["input"] in claims else evidence.get(a["input"], {}).get("version_status", "current")
                edges.append({"from": a["input"], "to": c["id"], "type": "drove" if a["drove"] else "context",
                              "share": a["share"], "on_path": a["drove"] and c["id"] in path and a["input"] in path,
                              "status": "replaced" if (src_status in ("retired", "replaced") and a["drove"]) else "current"})
        return {"columns": columns, "nodes": nodes, "edges": edges}

    # -- plain-language summary ----------------------------------------
    @staticmethod
    def _name(node_id: str) -> str:
        if node_id == "decision":
            return "the decision"
        if node_id.startswith("c") and node_id[1:].isdigit():
            return f"claim {int(node_id[1:]):02d}"
        return node_id

    def _bad_chain(self, report: dict, start: str = "decision") -> list[str]:
        """decision -> claim -> ... -> retired chunk, following replaced links."""
        chain, cur = [start], start
        claims, evidence = report["claims"], report["evidence"]
        while cur in claims and claims[cur]["replaced_via"]:
            nxt = claims[cur]["replaced_via"][0]
            chain.append(nxt)
            cur = nxt
            if cur in evidence:
                break
        return chain

    def analyst_read(self, report: dict) -> dict:
        d = (report.get("decision") or {}).get("value")
        rp = report.get("replay")
        f = report["finding"]
        days = report["days_out_of_date"]
        run = report["run"]
        claims, evidence = report["claims"], report["evidence"]
        sources: list[str] = []
        bad = [c for c in claims.values() if c["status"] == "replaced"]

        if run["status"] == "paused":
            ev = next((e for e in self.store.events(run["id"]) if e["kind"] == "breakpoint" and e["step"] == run["paused_at"]), None)
            headline = f"Run paused at step {run['paused_at']}. Nothing has been decided yet."
            text = ev["detail"]["message"] if ev else "A breakpoint rule fired."
            if rp and rp.get("decision_after"):
                text += f" Continuing with the current version leads to: {rp['decision_after']}."
            if bad:
                src = next((evidence[e] for e in bad[0]["replaced_via"] if e in evidence), None)
                sources = [src["label"] if src else "", f"Breakpoint at step {run['paused_at']}"]
            return {"headline": headline, "text": text, "sources": [s for s in sources if s]}

        if f in ("confirmed_by_replay", "decision_used_replaced", "outcome_unchanged", "claim_used_replaced"):
            first = min(bad, key=lambda c: c["step"])
            chain = self._bad_chain(report, "decision" if "decision" in claims and claims["decision"]["status"] == "replaced" else first["id"])
            src = evidence.get(chain[-1])
            label = src["label"] if src else "a replaced source"
            hops = [self._name(n) for n in chain[:-1]] + [label]
            story = f"{hops[0]} rests on {hops[1]}" + "".join(f", which rests on {h}" for h in hops[2:])
            story = story[0].upper() + story[1:]
            current = src["current_label"] if src else "the current version"
            sources = [label, f"Retrieval at step {src['step']}" if src else "", f"Replay {rp['run_id']}" if rp else ""]
            if f == "confirmed_by_replay":
                headline = f"{'Approved' if d == 'approve' else 'Decided'} on a policy retired {days} days earlier."
                text = (f"{story}. That version stopped applying on {fmt_day(src['retired_on']) if src else 'an earlier date'}. "
                        f"Replaying with {current} changes the decision from {rp['decision_before']} to {rp['decision_after']}.")
            elif f == "outcome_unchanged":
                headline = f"Used a policy retired {days} days earlier, but the outcome holds."
                text = (f"{story}. Replaying with {current} leaves the decision unchanged ({rp['decision_after']}). "
                        "The retrieval index should stop serving the retired version.")
            else:
                headline = f"A claim rests on a source retired {days} days earlier."
                text = f"{story}. It is not on the path to the decision, but should be corrected."
        elif f == "retired_in_context":
            headline = "A retired source was retrieved but did not drive any claim."
            text = "No claim depends on it. The retrieval index still serves the retired version."
        elif f == "unsourced":
            headline = "Evidence is current, but one claim has no source."
            ids = [c["id"] for c in report["claims"].values() if c["status"] == "nosource"]
            text = f"{', '.join(self._name(i).capitalize() for i in ids)} came from the model's own knowledge. A reviewer should confirm it."
        else:
            headline = "Every claim is backed by current evidence."
            text = "No replaced sources and no unsupported claims in this run."
        st = report.get("stability")
        if st and not st["stable"]:
            text += f" The decision is unstable: {', '.join(f'{v} {k}' for k, v in st['counts'].items())} out of {st['samples']} samples."
        return {"headline": headline, "text": text, "sources": [s for s in sources if s]}
