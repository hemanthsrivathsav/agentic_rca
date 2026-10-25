# Supersede — project context

Handoff from a planning conversation (Oct 2026). Read this before writing code.

## What we are building

**Supersede: Why-Trace for Agents.** A decision-provenance layer for AI agents. For any agent answer it shows, claim by claim:

1. what the agent claimed,
2. which evidence actually drove each claim,
3. whether that evidence was still valid (current version, fresh data, correct definition),
4. which agent and step first went wrong,
5. what the answer becomes when the run is replayed with corrected evidence.

Pitch line: *Tracers show what ran. Supersede shows why the agent decided, from which version of the truth, and what would change.* It is a layer on top of tracing tools (LangSmith, Langfuse), not a replacement.

- Hackathon: internal enterprise AI hackathon at a US bank. Judged on innovation, cross-domain reuse of enterprise capabilities, readiness, technical quality (including security).
- Track: **Agentic Development**.
- Team lead / designer: Hemanth (UI/UX).

## Hard constraints

- **No LangChain / LangGraph / LangSmith libraries.** Only company-approved libraries. Build the agent runtime, checkpoints, breakpoints and forking ourselves in plain Python. (May change; the user will say if LangChain becomes available.)
- **Minimal libraries.** Assume only: FastAPI + uvicorn, Python standard library (`sqlite3`, `json`, `time`, `uuid`, `difflib`, `dataclasses`, `urllib`), one HTTP client for Azure OpenAI (`httpx` if approved, else `urllib`), React + TypeScript on the frontend. No graph/charting libraries: the evidence graph is hand-positioned SVG + absolutely positioned nodes. Ask before adding any dependency.
- Dev machine: Windows laptop, VS Code.
- Backend: FastAPI (Flask and Streamlit also approved). Use **FastAPI**.
- Frontend: **React + TypeScript**. Styling with **vanilla CSS or SCSS only**, no CSS frameworks (no Tailwind, no MUI, no Bootstrap).
- Storage: not decided. Use **SQLite behind a small storage interface** so it can move to Postgres or Databricks Delta later.
- LLM: not yet approved. Ask for **Azure OpenAI**. Copilot / Copilot Studio agents are NOT suitable as observed agents: they run their own loop, so we cannot see retrieval, snapshot state, pause or fork them.
  - Build a swappable `LLMClient` interface with: `AzureOpenAIClient` (real) and `MockLLMClient` (deterministic, scripted, offline) so the demo always runs.
- All data is synthetic. Fictional bank: **Harborline Bank**. Label every screen "Synthetic data". Never use real customer data.

## Core model: claim → origin → validity check → path to decision → replay

Supersede must NOT depend only on versioned documents. Any input that shapes a claim is evidence:

| Origin of a claim | How it is traced | How it is checked |
|---|---|---|
| Data (SQL query result) | Match the number in the answer to the cell in the query result | Table freshness, filters, joins, certified metric definition |
| Tool output | Tool span inputs/outputs | Correct call, errors, timeouts |
| Another agent | Handoff span | Follow it back to that agent and check its origin |
| Document | Retrieved chunk IDs | Version + SUPERSEDES status |
| User input / instructions | Prompt span | Followed or ignored |
| Model's own knowledge | Nothing in context explains it | Label **Ungrounded**; test consistency across runs |

Honest limit to state in the pitch: claims from the model's own knowledge get no source, only an ungrounded flag and a consistency test.

## How "Decision used replaced policy" is detected

1. **Version records** (before runs): each doc section has id, version, effective date, retired date; new version has a `SUPERSEDES` edge to the old one at section level (v4 §2.1 → v3 §2.1). Every chunk carries `doc, version, section` metadata. Hand-written JSON for the demo.
2. **Record retrieval** (during run): retrieval step emits a span with returned chunk IDs.
3. **Version check** (deterministic): `stale = run_time > chunk.retired_on`; `days_out_of_date = run_time - retired_on` (demo: 106 days).
4. **Did it drive a claim?** Split output into atomic claims (LLM). **Leave-one-out**: remove the chunk, regenerate/re-score the claim; if it changes, the chunk *drove* it (score e.g. 0.82). Entailment check for *supports*. This is the only LLM-dependent step; keep 3–5 chunks.
5. **Path to decision**: follow handoff spans forward: stale chunk → claim 3 → claim 4 (risk score) → handoff → final decision.
6. **Confirm by replay**: swap v3 §2.1 for v4 §2.1 via the SUPERSEDES edge, re-run from that step. Decision changes → confirmed. No change → downgrade.

Label strength, weakest to strongest: Retired evidence in context → Claim used replaced policy → Decision used replaced policy → Confirmed by replay.

## Features beyond LangSmith / Langfuse (priority order)

Note: LangGraph already has checkpointing, node breakpoints and time travel, so don't pitch those as "nobody does this". Our angle is meaning-based triggers and evidence-level forks.

1. **Runtime breakpoints (P0, headline).** A rules engine checks each step before it executes. On a hit: stop, save state, wait. A person can inspect, edit state (swap v3→v4), resume or fork. Rules:
   - replaced/stale source entered context
   - tool loop: same tool + similar arguments 3+ times
   - ungrounded claim right before an irreversible action (approve account, write to table)
   - cost or step count over budget
2. **State and memory inspection (P1).** Runtime saves a full state snapshot after every step (messages, scratchpad, retrieved evidence, memory writes), stored as diffs. UI: scrubber over steps with added/removed items.
3. **Decision space (P1).** At a decision step: use token probabilities if Azure OpenAI exposes them; otherwise re-run that one step 5–10 times and count outcomes ("Approve 6/10, Escalate 4/10"). Optionally run the path not taken. Unstable decisions are a risk signal.
4. **Multi-agent drift detectors (P2, badge only).** Loops between agents, deadlock, goal drift (similarity of messages to the original task).
5. **Multi-modal (P3, limited).** Only scanned KYC documents: store OCR bounding boxes so a claim links to a region of the scanned page.

Also: claim-level quality strip (faithfulness, context relevance = chunks that drove nothing, answer relevance, consistency across runs), guard mode (block superseded chunks before generation, log the block), audit packet export (PDF + PROV-JSON, hash for tamper evidence).

## Demo scenario (main): KYC onboarding

- Agents: **Document agent** (parse docs, sanctions screening) → **Risk agent** (retrieve EDD policy, score risk) → **Decision agent** (merge findings, decide).
- Run **KYC-2041**, customer **Meridian Ledger LLC** (digital asset custody), run date **15 Oct 2026, 10:42**.
- **EDD Policy v3 §2.1**: "Escalate to EDD: money services businesses, casinos and dealers in precious metals." Retired **1 Jul 2026**.
- **EDD Policy v4 §2.1**: adds "virtual asset service providers, including custody and exchange businesses."
- Failure: Risk agent retrieves v3 (seed v3 to rank higher on lexical match so it fails reliably) → claim "Digital asset custody is not on the EDD escalation list" (drove 0.82) → "Risk score 22 of 100 (low)" → decision **Approve account**.
- Claims: (1) registration docs match registry — current; (2) two beneficial owners screened, no sanctions matches — current; (3) custody not on EDD list — replaced policy; (4) risk score 22 — replaced policy; (5) expected monthly volume fits business size — **no source**.
- Agent's self-reported explanation (shown separately, unverified): "I checked the latest Enhanced Due Diligence policy and this business type is not listed."
- Replay with v4 from step 3 (steps 1–2 cached): claim 3 → custody is a VASP, requires EDD; claim 4 → risk score 71 (high); decision → **Escalate to EDD review**. Claim 5 stays unsupported.
- Breakpoint version of the demo: run pauses when the Risk agent retrieves v3: "Paused: replaced policy entered context. Fork with v4?"

Other scenarios (closing slide, cross-domain reuse): customer-service chatbot quoting 2025 fee schedule; loan underwriting (fictional DTI change 43%→40%); AML alert triage (old runbook + ignored PEP note); branch manager scorecard data pipeline ("Active Customer" definition v1 vs v2, 18% vs 6% growth); Databricks text-to-SQL chatbot (overdraft fee revenue $4.2M vs $3.7M: 9-day-stale table, calendar vs fiscal quarter, gross vs certified net fee).

## Features inspired by LangGraph / LangSmith (built from scratch)

All rest on three building blocks; build these first and well:
1. **Step loop** that saves a checkpoint (JSON state) after every step to SQLite (`checkpoints`: run_id, step, state_json).
2. **Span recorder** wrapping every model/tool call: start/end via `time.perf_counter()`, tokens from the Azure response, inputs/outputs, chunk IDs.
3. **Resume from step k**: load checkpoint k, apply an edit (e.g. swap chunk v3→v4), run forward under a new run ID with `parent_run_id` and `forked_at`. Used by replay, fork, breakpoints and approve/edit.

Features on the decision page (in scope):
- **State drawer per step**: what the agent held (messages, retrieved chunks, scratchpad), diff vs previous step.
- **Fork from any step**, forks shown as branches under the scrubber.
- **Pause card actions: Approve / Edit state / Reject** (runtime sets `status=paused` and returns; resume uses block 3).
- **Cost and time row**: duration and tokens per step and per run.
- **Mark decision** (Correct / Wrong / Needs review) stored in a `feedback` table. "Save as test case" + regression runner is next.

Deferred: live token streaming (demo replays recorded steps instead), playground (re-run one step with an edited prompt), experiment comparison, failure clustering. Roadmap only: multi-modal beyond OCR boxes.

In the pitch, present these as standard tools built in; keep the spotlight on claim-level evidence, version status, meaning-based breakpoints and decision stability.

## UI (designs in `design/` folder)

Designs are `.dc.html` files (HTML with `{{holes}}` and a small logic class). Use them as visual reference; rebuild as React + TS components.

**Current direction is Version 2 (`design/v2/`).** Light, calm app shell with a dark teal "evidence canvas" for the graph. Inspired by Dribbble shots: AI Policy Intelligence network map (serif finding headline, "Analyst read" card, highlighted path), Vendor Risk propagation wave (quiet UI so the red problem is loudest), Supply Chain Digital Twin (left-to-right sequential graph, filters, graph/table toggle), Regulatory Intelligence constellation (time scrubber, insight cards on selection), Studio Ariel knowledge graph (status colours, graph + table), Machines That Conquered (dense network, one lit path, Play scrubber, story chapters).

- `v2/V2-Overview.dc.html` — Runs overview: dark "what needs attention" band (serif headline "7 decisions this week rest on a retired policy" + runs ranked by exposure), stat tiles, runs table with evidence-health bars and filter chips, "Recently replaced" timeline (policies, fee schedules, metric definitions, data refreshes).
- `v2/V2-Decision.dc.html` — Decision graph (main screen): left rail (run info, evidence-type filters, breakpoint rules, legend); dark canvas with serif finding headline, "As the agents ran it / With current policy" toggle, Graph/Table toggle, left-to-right graph (Evidence → Document agent → Risk agent → Decision agent → Outcome, node size = how much it drove the decision), animated flow along the failing path (coral) that re-routes through v4 (teal) in current mode, Play + 6-step scrubber that pauses at step 3 with "Fork with v4 and continue / Continue as is"; right panel: Analyst read (serif, sources, ask box), selected-node details, decision stability (6 approve / 4 escalate of 10 samples); stat strip under the canvas.
- v2 palette: shell ground #EEF1EF, surface #FFFFFF, ink #13201F, muted #5E6B6A, lines #DCE2DF; canvas #0E1D21, canvas text #E6EEEC, canvas muted #8FA6AB; replaced/problem coral #FF6A55 (on light: #C2412F), current teal #43C6AC (on light: #0E7A68), no source amber #F2B441 (on light: #8A5E00). Fonts: Public Sans (UI, tabular numbers) + Source Serif 4 (finding headlines, analyst read, quotes).
- Still to design in v2: state drawer, fork branches, cost/time row, pause card Approve/Edit/Reject, mark decision; Replay, Audit packet and Breakpoints inbox pages.

Version 1 (`design/v1/`, superseded but useful reference):

- `Main.dc.html` — Runs overview: summary cards, runs table with claim counts and finding badges.
- `Answer.dc.html` — Answer + evidence card: claims with status, quality strip, evidence card (quote, drove bar, v3 vs v4), agent's self-report separated.
- `Graph.dc.html` — Derivation path + per-agent timeline with first-wrong-step pin.
- `Replay.dc.html` — Replay with current truth: decision change, claim diff, guard mode toggle.
- `Audit.dc.html` — Audit packet for compliance reviewers.
- `Hero.dc.html` — **Signature screen**: "As the agents ran it / With current policy" toggle, "106 days" figure, policy version timeline with dashed connector, claims + evidence + steps all switch together.

v1 visual language: navy sidebar (#101826), off-white ground (#F6F6F3), IBM Plex Sans + Mono.

Design rules for all versions: status colours only for meaning, never colour alone (always a word or icon); calm and serious. The user rejected a playful version (stamps, tilted cards, highlighter) as childish. Styling is vanilla CSS/SCSS only.

## Suggested code structure

```
supersede/
  backend/
    supersede/
      llm/            # LLMClient interface, AzureOpenAIClient, MockLLMClient
      runtime/        # graph executor, state, checkpoints (diffs), interrupts, fork/resume
      tracing/        # span model (OTel GenAI-style names: invoke_agent, retrieval, execute_tool, chat)
      knowledge/      # versioned doc store, SUPERSEDES edges, simple retrieval (BM25, stdlib)
      provenance/     # claim splitting, leave-one-out attribution, entailment, version check, lineage
      rules/          # breakpoint rules engine
      sampling/       # decision-space sampler
      replay/         # swap evidence, rerun from step k, claim diff
      store/          # storage interface + SQLite
      demo/kyc/       # agents, synthetic customers, EDD v3/v4 docs
    api/              # FastAPI app
    tests/
  frontend/           # React + TS (Vite), vanilla CSS/SCSS
```

SQLite tables (first cut): `runs` (id, workflow, subject, status, parent_run_id, forked_at, created_at), `spans` (id, run_id, step, agent, kind, name, input_json, output_json, chunk_ids, tokens_in, tokens_out, started, ended), `checkpoints` (run_id, step, state_json), `doc_versions` (doc_id, section, version, text, effective_on, retired_on), `supersedes` (new_version_id, old_version_id), `claims` (id, run_id, step, agent, text), `attributions` (claim_id, evidence_id, drove, supports), `feedback` (run_id, verdict, note, author, at), `test_cases`.

## Build order

1. Storage interface + SQLite, synthetic KYC data (customers, EDD v3/v4, risk guide), `MockLLMClient` scripted to reproduce the demo exactly.
2. Runtime: step loop, checkpoints, span recorder, KYC agents as plain Python functions.
3. Resume-from-step-k (replay/fork) and the breakpoint rules engine (pause/approve/edit/reject).
4. Provenance: claim splitting, leave-one-out attribution, version check, lineage to decision, replay confirmation, decision-stability sampler.
5. FastAPI endpoints for runs, run detail, graph, steps/state, replay, fork, resume, feedback.
6. React + TS frontend for V2 Overview and V2 Decision, vanilla CSS.
7. Azure OpenAI client once access is approved; keep the mock for offline demos.
8. Tests (pytest if approved, else `unittest`) for detection, replay and breakpoints.

## Open questions

- LLM access (Azure OpenAI pending).
- Final storage choice.
- Exact list of approved Python/npm packages.
- Hackathon date and judges' profile (engineers vs product).

## Current status (25 Oct 2026)

Build order steps 1 to 6 and 8 are done; step 7 (Azure client) is written but untested until access is approved. See README.md for how to run.

- **Engine** (`backend/supersede/`, standard library only): `store.py`, `knowledge.py`, `llm.py` (MockLLMClient + AzureOpenAIClient over urllib), `tracing.py`, `runtime.py` (StepContext, Runner.start/resume/fork/rerun_step), `rules.py` (stale_evidence, tool_loop, ungrounded_before_action, budget), `provenance.py` (Analyzer), `service.py` (facade used by both APIs), `demo/kyc.py` + `demo/data/*.json`.
- **APIs**: `backend/api/app.py` (FastAPI) and `backend/api/stdlib_server.py` (same routes, no dependencies). Routes are listed in `backend/README.md`.
- **Tests**: `backend/tests/test_engine.py`, 22 tests, all passing (`python -m unittest discover -s tests`).
- **Frontend** (`frontend/src/`): Overview and Decision pages per design v2. Runs on the laptop against the FastAPI app (`python -m uvicorn`), `npm run typecheck` passes. Checked in headless Edge at 2560 and 1440 px wide: graph layout, Play with simulated breakpoint, fork animating in place, branches.
- **Rebuild spec**: `docs/REBUILD_SPEC.md` describes every file in enough detail to recreate the project, with expected demo results. Keep it in sync when behaviour changes.
- Dev machine: Smart App Control blocks unsigned `.exe` launchers, so always run `python -m pip`, `python -m uvicorn`, `python -m unittest`. Install packages into the main Python, not a venv.

Design decisions made while building:
- Attribution = leave-one-out on each claim's inputs; if no single input changes the claim, inputs are removed in pairs and the credit split (handles redundant causes, e.g. in the replay both claim 03 and claim 04 lead to escalation).
- An input "drove" a claim when it explains at least 20% of the change and hiding it changed the claim by at least 5% (`DROVE_SHARE`, `MIN_CHANGE` in provenance.py).
- Findings: healthy, unsourced, retired_in_context, claim_used_replaced, decision_used_replaced, outcome_unchanged, confirmed_by_replay.
- Replay is automatic: when a run used a retired chunk, the analyzer forks it from the earliest step that chunk entered, with every retired chunk swapped for its current version (fork reason "replay with current versions"), and diffs claims and decision.
- Demo runs: KYC-2041 Meridian Ledger (historical, no breakpoints, approve → replay escalate, 106 days out of date), KYC-2036 Tidewater Coin Exchange (breakpoints on, paused at step 3), KYC-2040/2039/2033 (read v3, outcome unchanged). The mock decision step gives 6 approve / 4 escalate across 10 samples for low-risk cases because claim 05 has no source.
- Graph layout follows design v2 and depends only on structure (claims step down in run order, evidence level with the claim it feeds, versions of one source grouped, decision centred). A fork's graph keeps the version it swapped out (status `swapped_out`), so a run and its forks have the same nodes and the Decision page animates between them in place instead of reloading.
- Forking reuses an identical fork (same step, same options): with the mock model a copy would be exactly the same run. The service lock stops simultaneous requests from creating duplicate replays.
- The Branches row under the canvas is not in design v2; it came from the "fork branches" feature above and still needs a v2 design.

Next ideas: "save as test case" + regression runner, Breakpoints inbox page, Replay and Audit packet pages in v2 style, text-to-SQL data-agent demo (data evidence type).
