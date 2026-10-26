# Supersede backend

## Run

From this folder (`backend/`). Use `python -m ...`: on Windows with Smart App Control the `pip.exe` and `uvicorn.exe` launchers are blocked.

```powershell
python -m pip install -r requirements.txt
python -m uvicorn api.app:app --reload --port 8000   # API on http://127.0.0.1:8000
python -m api.stdlib_server                          # same routes, no FastAPI needed
python -m unittest discover -s tests -v              # 22 engine tests, standard library only
```

Then start the frontend with `npm run dev` in `../frontend`.

## Layout

- `supersede/`: the engine. Python standard library only.
- `api/app.py`: FastAPI app.
- `api/stdlib_server.py`: the same routes without FastAPI.
- `tests/test_engine.py`: unit tests.

Environment variables: `SUPERSEDE_DB` (SQLite file, default `supersede.db`), `SUPERSEDE_LLM` (`mock` or `azure`), and `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_KEY`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_API_VERSION` for Azure.

Analyses are cached in the database. A cached report is rebuilt when the run's status changes or when `REPORT_VERSION` in `provenance.py` is bumped (do that whenever the report shape changes).

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | `{"ok": true, "llm": "mock"}` |
| GET | `/api/overview` | Totals, runs ranked by exposure, recently replaced sources |
| GET | `/api/runs` | Run summaries (top-level runs; `?include_forks=true` for all) |
| POST | `/api/runs` | Start a run: `{"customer_id": "KYC-2041", "options": {"breakpoints": true}}` |
| GET | `/api/runs/{id}` | Full report: claims (each with a `proof`: the experiments behind it and a verdict), attribution, evidence status, decision path, replay, stability, steps, graph, events, forks (`?refresh=true` re-analyses) |
| GET | `/api/runs/{id}/steps/{n}/state` | State after step n, what changed, and the spans of that step |
| POST | `/api/runs/{id}/resume` | Act on a paused run: `{"action": "approve" \| "edit" \| "reject", "swaps": {...}}` |
| POST | `/api/runs/{id}/fork` | Re-run from a step with edited evidence: `{"from_step": 3, "swaps": {"old-chunk": "new-chunk"}, "guard": false}`. If the run already has a fork from that step with the same settings, that fork is returned instead of a copy |
| POST | `/api/runs/{id}/rules` | Turn a breakpoint rule on or off: `{"key": "stale_evidence", "on": true}` |
| POST | `/api/runs/{id}/feedback` | Mark the decision: `{"verdict": "correct" \| "wrong" \| "needs_review", "note": ""}` |
| POST | `/api/demo/reset` | Delete everything (forks included) and re-create the demo runs |

Requests are served on several threads. The service runs anything that can create runs (analysing a new run creates its replay, forking, resuming) under one lock, so two simultaneous requests never produce duplicate forks.
