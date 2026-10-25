
# Run Book
frontend :
> npm run dev


backend :
>python -m uvicorn api.app:app --reload 

# Supersede backend

- `supersede/`: the engine. Python standard library only.
- `api/app.py`: FastAPI app (`uvicorn api.app:app --reload --port 8000`).
- `api/stdlib_server.py`: the same routes without FastAPI (`python -m api.stdlib_server`).
- `tests/`: `python -m unittest discover -s tests -v`.

Environment variables: `SUPERSEDE_DB` (SQLite file, default `supersede.db`), `SUPERSEDE_LLM` (`mock` or `azure`), and `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_KEY`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_API_VERSION` for Azure.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/overview` | Totals, runs ranked by exposure, recently replaced sources |
| GET | `/api/runs` | Run summaries (top-level runs; `?include_forks=true` for all) |
| POST | `/api/runs` | Start a run: `{"customer_id": "KYC-2041", "options": {"breakpoints": true}}` |
| GET | `/api/runs/{id}` | Full report: claims, attribution, evidence status, decision path, replay, stability, steps, graph, events, forks |
| GET | `/api/runs/{id}/steps/{n}/state` | State after step n, what changed, and the spans of that step |
| POST | `/api/runs/{id}/resume` | Act on a paused run: `{"action": "approve" \| "edit" \| "reject", "swaps": {...}}` |
| POST | `/api/runs/{id}/fork` | Re-run from a step with edited evidence: `{"from_step": 3, "swaps": {"old-chunk": "new-chunk"}}` |
| POST | `/api/runs/{id}/rules` | Turn a breakpoint rule on or off: `{"key": "stale_evidence", "on": true}` |
| POST | `/api/runs/{id}/feedback` | Mark the decision: `{"verdict": "correct" \| "wrong" \| "needs_review", "note": ""}` |
| POST | `/api/demo/reset` | Delete everything and re-create the demo runs |
