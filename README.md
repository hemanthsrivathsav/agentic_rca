# Supersede

Decision provenance for AI agents. For every agent answer, Supersede shows which evidence drove each claim, whether that evidence was still valid, where the run first went wrong, and what changes when the run is replayed with current information. It can also pause a run *before* the damage, when a meaning-based rule fires (for example "a replaced policy entered the context").

Hackathon project. All data is synthetic (fictional Harborline Bank).

## Run it (Windows, VS Code)

You need Python 3.10+ and Node.js 20.19+ (or 22.12+, required by Vite 8).

Run Python tools as `python -m <tool>` (`python -m pip`, `python -m uvicorn`). On machines with Windows Smart App Control or Device Guard, the `.exe` launchers such as `pip.exe` and `uvicorn.exe` are blocked because they are unsigned; `python.exe` is signed and allowed.

**1. Backend** (terminal 1)

```powershell
cd D:\Projects\agent_rca\backend
python -m pip install -r requirements.txt
python -m uvicorn api.app:app --reload --port 8000
```

No FastAPI allowed? The same API runs on the standard library alone:

```powershell
cd D:\Projects\agent_rca\backend
python -m api.stdlib_server
```

**2. Frontend** (terminal 2)

```powershell
cd D:\Projects\agent_rca\frontend
npm install
npm run dev
```

Open http://localhost:5173. The demo data (5 KYC runs) is created on first start in `backend/supersede.db`. "Reset demo data" on the Runs page puts it back and removes any forks you made.

The UI uses the full width of large screens: the graph spreads out and scales up on wide monitors, and scales down (then scrolls) on narrow ones.

**3. Tests** (engine only, standard library)

```powershell
cd D:\Projects\agent_rca\backend
python -m unittest discover -s tests -v
```

**One-server option:** `npm run build` in `frontend/`, then start either backend. It serves the built UI at http://localhost:8000.

## Demo script (about 3 minutes)

1. **Runs page.** "1 decision rests on a retired policy." KYC-2041 is ranked first. Every run was marked successful by normal tracing.
2. **Open the worst case (KYC-2041).** The coral path runs from EDD Policy v3 (retired 106 days earlier) through claim 03 and claim 04 to "Approve account". Each piece of evidence sits level with the claim it fed, and v4 (in force, never retrieved) sits just under v3. Click nodes to see what drove each claim, measured by removing inputs one at a time.
3. **Press Play.** The run rebuilds step by step and stops at step 3: "With breakpoints on, this run would pause at step 3."
4. **Fork with v4 §2.1 and continue.** Nothing reloads: the toggle moves to "With current versions", the evidence re-points from v3 to v4 (v3 stays, dimmed and marked "swapped out"), the flow turns teal, and steps 4 to 6 play on until the outcome becomes "Escalate to EDD". This is the automatic replay (steps 1 and 2 reused), which the page already has. The decision-stability card goes from 6 approve / 4 escalate to 10 of 10 escalate.
5. **Toggle back to "As the agents ran it"** to compare the two on the same layout.
6. **Inspect state at step 3.** The drawer shows exactly what entered the agent's context, the claims made, and the calls with time and tokens.
7. **Open KYC-2036 (paused).** A live breakpoint. "Swap in the current version" forks the run with v4 and plays on in place. It pauses again before the irreversible decision because claim 05 has no source. "Approve and continue" finishes with an escalation.

Forking the same run the same way twice (same step, same swap) opens the existing fork instead of making a copy, so the Branches row under the canvas stays short.

## How it works

| Piece | File | What it does |
|---|---|---|
| Storage | `backend/supersede/store.py` | SQLite behind a small interface (swap for Postgres or Delta later) |
| Versioned knowledge | `backend/supersede/knowledge.py` | Document sections with effective/retired dates, SUPERSEDES edges, BM25 retrieval, guard mode |
| Model clients | `backend/supersede/llm.py` | Offline scripted mock (default) and Azure OpenAI over plain HTTPS |
| Tracing | `backend/supersede/tracing.py` | Spans for every agent step, model call, tool call and retrieval, with time and tokens |
| Runtime | `backend/supersede/runtime.py` | Step loop with a checkpoint after every step; resume, fork from any step with edited evidence (an identical fork is reused) |
| Breakpoint rules | `backend/supersede/rules.py` | Replaced source entered, tool loop, unsupported claim before an irreversible step, model-call budget |
| Provenance | `backend/supersede/provenance.py` | Leave-one-out attribution (with a pair-wise fallback for redundant causes), version checks, decision path, replay diff, stability sampling, graph for the UI |
| Demo | `backend/supersede/demo/` | Three-agent KYC workflow, synthetic customers, EDD Policy v3/v4 |
| Service | `backend/supersede/service.py` | The one object both APIs call; caches analyses and serialises work that can create runs, so simultaneous requests never make duplicate replays |
| API | `backend/api/app.py`, `backend/api/stdlib_server.py` | FastAPI app, and the same routes on the standard library |
| UI | `frontend/src/` | React + TypeScript, plain CSS, hand-drawn SVG graph, no UI or graph libraries. A run, its replay and its forks share one graph layout, so switching between them animates instead of reloading |

## Using a real model

```powershell
$env:SUPERSEDE_LLM = "azure"
$env:AZURE_OPENAI_ENDPOINT = "https://<your-resource>.openai.azure.com"
$env:AZURE_OPENAI_KEY = "<key>"
$env:AZURE_OPENAI_DEPLOYMENT = "<deployment name>"
```

Then start the backend as above. Leave-one-out attribution and stability sampling make extra model calls (about 5 per claim and 10 per decision), so keep the demo to a handful of runs.

## Folders

- `CLAUDE.md`: every product and technical decision. Claude Code reads it automatically.
- `docs/REBUILD_SPEC.md`: detailed spec of every file, enough for a coding agent to rebuild the project, with the expected demo results.
- `docs/observability-gaps.md`: the original notes on what LLM observability tools miss.
- `design/v2/`: current UI designs. `design/v1/`: first version.
- `backend/`: Python engine (standard library only) and API.
- `frontend/`: React + TypeScript app.
