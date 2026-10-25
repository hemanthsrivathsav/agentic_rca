"""Engine tests. Standard library only: run with ``python -m unittest`` from backend/."""

import unittest

from supersede.demo import kyc
from supersede.runtime import Runner, Step, Workflow
from supersede.rules import ToolLoopRule, BudgetRule, default_rules
from supersede.service import Supersede
from supersede.store import SQLiteStore

V3, V4 = "edd-policy@v3#2.1", "edd-policy@v4#2.1"


def service() -> Supersede:
    s = Supersede(SQLiteStore(":memory:"), llm="mock")
    s.seed_demo()
    return s


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.kb = kyc.knowledge()

    def test_versions(self):
        self.assertEqual(self.kb.status_on(V3, "2026-06-30"), "current")
        self.assertEqual(self.kb.status_on(V3, "2026-07-01"), "retired")
        self.assertEqual(self.kb.days_out_of_date(V3, "2026-10-15"), 106)
        self.assertEqual(self.kb.current_version(V3, "2026-10-15"), V4)
        self.assertEqual(self.kb.current_version(V3, "2026-03-01"), V3)

    def test_plain_retrieval_prefers_retired_version(self):
        hits = self.kb.search("enhanced due diligence escalation list business types standard onboarding", top_k=2, doc_ids=["edd-policy", "risk-guide"])
        self.assertEqual(hits[0][0], V3)
        self.assertNotIn(V4, [h for h, _ in hits])

    def test_guard_mode_swaps_retired_chunk(self):
        res = self.kb.retrieve("enhanced due diligence escalation list", top_k=2, doc_ids=["edd-policy"], guard_day="2026-10-15")
        self.assertEqual(res["chunks"][0]["id"], V4)
        self.assertEqual(res["blocked"], [{"from": V3, "to": V4}])


class RunTests(unittest.TestCase):
    def setUp(self):
        self.s = service()

    def test_historical_run_approves_on_retired_policy(self):
        rep = self.s.report("KYC-2041")
        self.assertEqual(rep["decision"]["value"], "approve")
        self.assertEqual(rep["finding"], "confirmed_by_replay")
        self.assertEqual(rep["days_out_of_date"], 106)
        self.assertEqual(rep["first_wrong_step"]["step"], 3)
        self.assertEqual(rep["claims"]["c3"]["status"], "replaced")
        self.assertEqual(rep["claims"]["c4"]["status"], "replaced")
        self.assertEqual(rep["claims"]["c5"]["status"], "nosource")
        self.assertEqual(rep["claims"]["c1"]["status"], "current")
        self.assertIn(f"ev:{V3}", rep["decision_path"])

    def test_replay_flips_decision(self):
        rp = self.s.report("KYC-2041")["replay"]
        self.assertEqual((rp["decision_before"], rp["decision_after"]), ("approve", "escalate"))
        self.assertTrue(rp["decision_changed"])
        changed = {c["id"] for c in rp["claims"] if c["changed"]}
        self.assertEqual(changed, {"c3", "c4", "decision"})
        child = self.s.report(rp["run_id"])
        self.assertEqual(child["run"]["forked_at"], 3)
        self.assertTrue(all(s["cached"] for s in child["steps"] if s["step"] < 3))

    def test_outcome_unchanged_when_policy_change_is_irrelevant(self):
        self.assertEqual(self.s.report("KYC-2040")["finding"], "outcome_unchanged")

    def test_stability(self):
        st = self.s.report("KYC-2041")["stability"]
        self.assertEqual(st["counts"], {"approve": 6, "escalate": 4})
        self.assertFalse(st["stable"])
        replay = self.s.report(self.s.report("KYC-2041")["replay"]["run_id"])
        self.assertEqual(replay["stability"]["counts"], {"escalate": 10})

    def test_attribution_finds_the_driving_chunk(self):
        attr = {a["input"]: a for a in self.s.report("KYC-2041")["claims"]["c3"]["attribution"]}
        self.assertTrue(attr[f"ev:{V3}"]["drove"])
        self.assertFalse(attr["ev:risk-guide@v2#1"]["drove"])

    def test_redundant_causes_share_credit(self):
        # In the replay both claim 03 and claim 04 lead to escalation on their own.
        rep = self.s.report(self.s.report("KYC-2041")["replay"]["run_id"])
        att = {a["input"]: a for a in rep["claims"]["decision"]["attribution"]}
        self.assertTrue(att["c3"]["drove"] and att["c4"]["drove"])
        self.assertIn("ev:edd-policy@v4#2.1", rep["decision_path"])

    def test_graph_shape(self):
        g = self.s.report("KYC-2041")["graph"]
        ids = {n["id"] for n in g["nodes"]}
        self.assertIn(f"ev:{V4}", ids)                      # current version shown though not retrieved
        self.assertTrue(any(e["type"] == "replaces" for e in g["edges"]))
        self.assertEqual(g["columns"][0], "Evidence")
        self.assertEqual(g["columns"][-1], "Outcome")


class BreakpointTests(unittest.TestCase):
    def setUp(self):
        self.s = service()

    def test_pauses_when_retired_policy_enters(self):
        run = self.s.store.get_run("KYC-2036")
        self.assertEqual((run["status"], run["paused_at"], run["pause_reason"]), ("paused", 3, "stale_evidence"))
        self.assertIsNone(self.s.store.checkpoint("KYC-2036", 4))

    def test_edit_forks_with_current_version_then_pauses_before_decision(self):
        rep = self.s.resume("KYC-2036", "edit")
        self.assertEqual(rep["run"]["parent_run_id"], "KYC-2036")
        self.assertEqual(rep["run"]["status"], "paused")
        self.assertEqual(rep["run"]["pause_reason"], "ungrounded_before_action")
        self.assertEqual(self.s.store.get_run("KYC-2036")["status"], "forked")
        done = self.s.resume(rep["run"]["id"], "approve")
        self.assertEqual(done["run"]["status"], "completed")
        self.assertEqual(done["decision"]["value"], "escalate")

    def test_approve_and_reject(self):
        rep = self.s.resume("KYC-2036", "approve")
        self.assertEqual(rep["run"]["pause_reason"], "ungrounded_before_action")
        rej = self.s.resume(rep["run"]["id"], "reject")
        self.assertEqual(rej["run"]["status"], "rejected")
        self.assertIsNone(self.s.store.checkpoint("KYC-2036", 6))

    def test_state_drawer(self):
        st = self.s.state("KYC-2041", 3)
        self.assertIn(f"ev:{V3}", st["diff"]["evidence"]["added"])
        self.assertEqual(st["diff"]["claims"]["added"], ["c3"])
        self.assertTrue(any(sp["kind"] == "retrieval" for sp in st["spans"]))

    def test_tool_loop_rule(self):
        def loop(ctx):
            for _ in range(3):
                ctx.tool("lookup", lambda q: {"q": q}, label="Lookup", q="same")
        store = SQLiteStore(":memory:")
        wf = Workflow("loop", [Step("loop", "Loop", "Agent", loop), Step("next", "Next", "Agent", lambda ctx: None)])
        r = Runner(store, kyc.knowledge(), kyc.mock_llm(), wf, [ToolLoopRule()])
        rid = r.start(subject="x", inputs={}, run_time="2026-10-15")
        self.assertEqual(store.get_run(rid)["pause_reason"], "tool_loop")

    def test_budget_rule(self):
        store = SQLiteStore(":memory:")
        r = Runner(store, kyc.knowledge(), kyc.mock_llm(), kyc.workflow(), [BudgetRule()])
        rid = r.start(subject="x", inputs=kyc.customer_inputs(kyc.customers()[0]), run_time="2026-10-15",
                      options={"rules": {"budget": True}, "model_call_limit": 2})
        self.assertEqual(store.get_run(rid)["pause_reason"], "budget")

    def test_guard_mode_run(self):
        rep = self.s.fork("KYC-2041", from_step=3, guard=True, reason="guard test")
        self.assertEqual(rep["decision"]["value"], "escalate")
        self.assertTrue(any(e["kind"] == "blocked" for e in rep["events"]))


class ServiceTests(unittest.TestCase):
    def test_overview(self):
        s = service()
        ov = s.overview()
        self.assertEqual(ov["totals"]["runs"], 5)
        self.assertEqual(ov["totals"]["paused"], 1)
        self.assertEqual(ov["ranked"][0]["id"], "KYC-2041")
        self.assertEqual(ov["replaced"][0]["new"], "EDD Policy v4 §2.1")

    def test_feedback(self):
        s = service()
        out = s.add_feedback("KYC-2041", "wrong", "should have escalated")
        self.assertEqual(out["feedback"][0]["verdict"], "wrong")
        with self.assertRaises(ValueError):
            s.add_feedback("KYC-2041", "maybe")


if __name__ == "__main__":
    unittest.main()
