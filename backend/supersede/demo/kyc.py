"""Synthetic KYC onboarding workflow (fictional Harborline Bank).

Three agents, six steps:

1. Document agent  parse documents     registry tool       -> claim c1
2. Document agent  sanctions check     screening tool      -> claim c2
3. Risk agent      retrieve EDD policy retrieval + model   -> claim c3
4. Risk agent      score risk          model               -> claim c4
5. Decision agent  check volume        model, no evidence  -> claim c5 (ungrounded)
6. Decision agent  decide              model               -> decision (irreversible)

The prompts carry labelled lines (``BUSINESS:``, ``POLICY:`` ...) so the same
prompts work with a real model and with the offline mock script below.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..knowledge import KnowledgeBase
from ..llm import MockLLMClient
from ..runtime import Step, StepContext, Workflow

DATA = Path(__file__).parent / "data"

VASP_TYPES = {"digital asset custody", "virtual asset exchange"}
CLASSIC_EDD_TYPES = {"money services business", "casino", "precious metals dealer"}


# --------------------------------------------------------------------------
# Fake tools
# --------------------------------------------------------------------------

def registry_lookup(name: str, match: bool) -> dict:
    return {"registered_name": name if match else name + " Holdings", "status": "active", "match": match}


def sanctions_screen(owners: list[str]) -> dict:
    return {"screened": len(owners), "matches": 0, "lists": ["OFAC SDN", "UN consolidated"]}


# --------------------------------------------------------------------------
# Agents (one function per step)
# --------------------------------------------------------------------------

SYSTEM = "You are a KYC onboarding agent at a bank. Answer in one sentence, using only the evidence given."


def parse_documents(ctx: StepContext) -> None:
    inp = ctx.state["inputs"]
    ev = ctx.tool("registry_lookup", registry_lookup, label="State business registry", name=inp["name"], match=inp["registry_match"])
    user = f"CUSTOMER: {inp['name']}\nREGISTRY: {ev['text'] if ev else 'unavailable'}\nTask: do the registration documents match the registry?"
    text = ctx.chat("verify_registration", SYSTEM, user)
    ctx.claim("c1", text, inputs=[ev["id"]] if ev else [])


def sanctions_check(ctx: StepContext) -> None:
    inp = ctx.state["inputs"]
    ev = ctx.tool("sanctions_screen", sanctions_screen, label="Sanctions screening", owners=inp["beneficial_owners"])
    user = f"OWNERS: {', '.join(inp['beneficial_owners'])}\nSCREENING: {ev['text'] if ev else 'unavailable'}\nTask: summarise the sanctions screening."
    text = ctx.chat("sanctions_summary", SYSTEM, user)
    ctx.claim("c2", text, inputs=[ev["id"]] if ev else [])
    ctx.handoff("Decision agent", ["c1", "c2"])


def retrieve_edd(ctx: StepContext) -> None:
    inp = ctx.state["inputs"]
    chunks = ctx.retrieve(
        "enhanced due diligence escalation list business types standard onboarding",
        top_k=2, doc_ids=["edd-policy", "risk-guide"],
    )
    policy = [c for c in chunks if c["doc_id"] == "edd-policy"]
    lines = "\n".join(f"POLICY [{c['label']}]: {c['text']}" for c in policy) or "POLICY: none retrieved"
    user = f"BUSINESS: {inp['business_type']}\n{lines}\nTask: is this business type on the EDD escalation list?"
    text = ctx.chat("classify_edd", SYSTEM, user)
    ctx.claim("c3", text, inputs=[c["id"] for c in chunks])
    ctx.note("retrieved", [c["label"] for c in chunks])


def score_risk(ctx: StepContext) -> None:
    inp = ctx.state["inputs"]
    finding = ctx.upstream_claims(["c3"])
    guide = [e for e in ctx.state["evidence"].values() if e.get("doc_id") == "risk-guide" and e["id"] not in ctx.exclude]
    user = (
        f"BUSINESS: {inp['business_type']}\nBASE_RISK: {inp['base_risk']}\n"
        f"EDD_FINDING: {finding[0]['text'] if finding else 'none'}\n"
        f"RISK_GUIDE: {guide[0]['text'] if guide else 'none'}\nTask: give a risk score from 0 to 100."
    )
    text = ctx.chat("score_risk", SYSTEM, user)
    score = int(re.search(r"(\d+) of 100", text).group(1)) if re.search(r"(\d+) of 100", text) else None
    ctx.claim("c4", text, inputs=[c["id"] for c in finding] + [g["id"] for g in guide], value=score)
    ctx.handoff("Decision agent", ["c3", "c4"])


def check_volume(ctx: StepContext) -> None:
    inp = ctx.state["inputs"]
    user = f"CUSTOMER: {inp['name']}\nBUSINESS: {inp['business_type']}\nTask: does the expected monthly volume fit the business size?"
    text = ctx.chat("check_volume", SYSTEM, user)
    # No evidence was retrieved for this claim: it comes from model knowledge.
    ctx.claim("c5", text, inputs=[])


def decide(ctx: StepContext) -> None:
    claims = ctx.upstream_claims(["c1", "c2", "c3", "c4", "c5"])
    lines = "\n".join(f"CLAIM {c['id']}: {c['text']}" for c in claims)
    user = f"{lines}\nTask: approve the account, or escalate it to enhanced due diligence?"
    text = ctx.chat("decide", SYSTEM, user)
    low = text.lower()
    value = "escalate" if "escalate" in low else "approve" if "approve" in low else "refer"
    ctx.decide(value, text, inputs=[c["id"] for c in claims])


def workflow() -> Workflow:
    return Workflow("kyc_onboarding", [
        Step("parse_documents", "Parse documents", "Document agent", parse_documents),
        Step("sanctions_check", "Sanctions check", "Document agent", sanctions_check),
        Step("retrieve_edd", "Retrieve EDD policy", "Risk agent", retrieve_edd),
        Step("score_risk", "Score risk", "Risk agent", score_risk),
        Step("check_volume", "Check volume", "Decision agent", check_volume),
        Step("decide", "Decide", "Decision agent", decide, irreversible=True),
    ])


# --------------------------------------------------------------------------
# Offline mock model: reproduces the demo deterministically
# --------------------------------------------------------------------------

def _field(user: str, name: str) -> str:
    m = re.search(rf"^{name}: (.*)$", user, re.M)
    return m.group(1).strip() if m else ""


def mock_script(purpose: str, messages: list[dict], sample: int) -> str:
    user = messages[-1]["content"]
    if purpose == "verify_registration":
        reg = _field(user, "REGISTRY")
        if reg == "unavailable":
            return "Registration could not be verified against the registry."
        return ("Registration documents match the state business registry."
                if json.loads(reg).get("match") else "Registration details do not match the state business registry.")

    if purpose == "sanctions_summary":
        scr = _field(user, "SCREENING")
        if scr == "unavailable":
            return "Sanctions screening results are unavailable."
        n = json.loads(scr)["screened"]
        word = {1: "One beneficial owner was", 2: "Two beneficial owners were", 3: "Three beneficial owners were"}.get(n, f"{n} beneficial owners were")
        return f"{word} screened against sanctions lists with no matches."

    if purpose == "classify_edd":
        business = _field(user, "BUSINESS")
        policies = re.findall(r"^POLICY \[(.*?)\]: (.*)$", user, re.M)
        label = business.capitalize()
        if not policies:
            return f"No EDD escalation rule was found for {business}."
        for name, text in policies:
            t = text.lower()
            if business in VASP_TYPES and "virtual asset" in t:
                return f"{label} is a virtual asset service provider, which requires EDD under {name}."
            if business in CLASSIC_EDD_TYPES and business.split()[0] in t:
                return f"{label} is on the EDD escalation list under {name}."
        return f"{label} is not on the EDD escalation list."

    if purpose == "score_risk":
        base = int(_field(user, "BASE_RISK") or 30)
        finding = _field(user, "EDD_FINDING")
        guide = _field(user, "RISK_GUIDE")
        if finding == "none":
            score = 45
        elif "requires edd" in finding.lower() or "on the edd escalation list under" in finding.lower():
            score = max(71, base + 45)
        else:
            score = base
        if guide == "none":
            return f"Risk score {score} of 100."
        band = "low" if score < 40 else "medium" if score < 70 else "high"
        tail = {"low": "so no enhanced due diligence is needed", "medium": "so a manual review is advised", "high": "so enhanced due diligence is required"}[band]
        return f"Risk score {score} of 100 ({band}), {tail}."

    if purpose == "check_volume":
        return "Expected monthly volume fits the stated business size."

    if purpose == "decide":
        m = re.search(r"Risk score (\d+) of 100", user)
        if "requires edd" in user.lower() or (m and int(m.group(1)) >= 40):
            return "Escalate to enhanced due diligence review."
        if not m:
            return "Refer to an analyst: the risk score is missing."
        score = int(m.group(1))
        # Low risk, but one claim (volume) has no source, so a sampled model is
        # unsure: 6 of 10 samples approve, 4 escalate. At temperature 0 it approves.
        if "monthly volume" in user and sample % 10 >= 6:
            return "Escalate to enhanced due diligence review."
        return "Approve account. Low risk, no enhanced due diligence required."

    return "No answer."


def knowledge() -> KnowledgeBase:
    return KnowledgeBase.from_json(DATA / "knowledge.json")


def customers() -> list[dict]:
    return json.loads((DATA / "customers.json").read_text(encoding="utf-8"))


def mock_llm() -> MockLLMClient:
    return MockLLMClient(mock_script)


def customer_inputs(c: dict) -> dict:
    keys = ["name", "business_type", "business_label", "base_risk", "beneficial_owners", "registry_match"]
    return {k: c[k] for k in keys}
