# Supersede

Decision provenance for AI agents. For every agent answer, Supersede shows which evidence drove each claim, whether that evidence was still valid, where the run first went wrong, and what changes when the run is replayed with current information. It can also pause a run *before* the damage, when a meaning-based rule fires (for example "a replaced policy entered the context").

Hackathon project. All data is synthetic (fictional Harborline Bank).

## Run it (Windows, VS Code)

You need Python 3.10+ and Node.js 18+.

**1. Backend** (terminal 1)

```powershell
cd D:\Projects\agent_rca\backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn api.app:app --reload --port 8000
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

Open http://localhost:5173. The demo data (5 KYC runs) is created on first start. "Reset demo data" on the Runs page puts it back.

**3. Tests** (engine only, standard library)

```powershell
cd D:\Projects\agent_rca\backend
python -m unittest discover -s tests -v
```

**One-server option:** `npm run build` in `frontend/`, then start either backend. It serves the built UI at http://localhost:8000.

## Demo script (about 3 minutes)

1. **Runs page.** "1 decision rests on a retired policy." KYC-2041 is ranked first. Every run was marked successful by normal tracing.
2. **Open the worst case (KYC-2041).** The coral path runs from EDD Policy v3 (retired 106 days earlier) through claim 03 and claim 04 to "Approve account". Click nodes to see what drove each claim, measured by removing inputs one at a time.
3. **Press Play.** The run rebuilds step by step and stops at step 3: "With breakpoints on, this run would pause here."
4. **Switch to "With current versions".** The replay swaps in v4 from step 3 (steps 1 and 2 reused) and the decision becomes "Escalate to EDD". The decision-stability card goes from 6 approve / 4 escalate to 10 of 10 escalate.
5. **Inspect state at step 3.** The drawer shows exactly what entered the agent's context, the claims made, and the calls with time and tokens.
6. **Open KYC-2036 (paused).** A live breakpoint. "Swap in the current version" forks the run with v4. It pauses again before the irreversible decision because claim 05 has no source. "Approve and continue" finishes with an escalation.

## How it works

| Piece | File | What it does |
|---|---|---|
| Storage | `backend/supersede/store.py` | SQLite behind a small interface (swap for Postgres or Delta later) |
| Versioned knowledge | `backend/supersede/knowledge.py` | Document sections with effective/retired dates, SUPERSEDES edges, BM25 retrieval, guard mode |
| Model clients | `backend/supersede/llm.py` | Offline scripted mock (default) and Azure OpenAI over plain HTTPS |
| Tracing | `backend/supersede/tracing.py` | Spans for every agent step, model call, tool call and retrieval, with time and tokens |
| Runtime | `backend/supersede/runtime.py` | Step loop with a checkpoint after every step; resume, fork from any step with edited evidence |
| Breakpoint rules | `backend/supersede/rules.py` | Replaced source entered, tool loop, unsupported claim before an irreversible step, model-call budget |
| Provenance | `backend/supersede/provenance.py` | Leave-one-out attribution (with a pair-wise fallback for redundant causes), version checks, decision path, replay diff, stability sampling, graph for the UI |
| Demo | `backend/supersede/demo/` | Three-agent KYC workflow, synthetic customers, EDD Policy v3/v4 |
| API | `backend/api/app.py`, `backend/api/stdlib_server.py` | FastAPI app, and the same routes on the standard library |
| UI | `frontend/src/` | React + TypeScript, plain CSS, hand-drawn SVG graph, no UI or graph libraries |

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
- `design/v2/`: current UI designs. `design/v1/`: first version.
- `backend/`: Python engine (standard library only) and API.
- `frontend/`: React + TypeScript app.
