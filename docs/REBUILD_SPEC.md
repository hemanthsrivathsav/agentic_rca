# Supersede rebuild spec

This file describes the whole Supersede codebase in enough detail for a coding agent to write it again from nothing. The rebuilt code should behave the same as the current code: same files, same data shapes, same user-visible text, same demo results. Product reasoning and design history are in `CLAUDE.md` and are not repeated here.

**How to use this spec**

1. Build in the order of section 13. Every step can be checked before the next one starts.
2. Treat everything in `code font` as exact: file names, function names, keys, ids, constants and quoted strings. Many quoted strings appear in the UI or are checked by the tests.
3. The work is done when every test in section 7.14 passes and the demo values in section 12 come out the same.

Contents: 1 Product summary · 2 Tech constraints · 3 Repository layout · 4 Shared vocabulary · 5 Data model · 6 Demo data · 7 Backend modules · 8 HTTP API · 9 Frontend · 10 Styles · 11 Non-code assets · 12 Expected demo results · 13 Build order · 14 Quirks to keep

---

## 1. Product summary

Supersede is a decision-provenance layer for AI agents. It runs a multi-agent workflow and records every model call, tool call and retrieval as a span. It saves the full agent state after every step. For each claim an agent makes, it then works out:

- **which inputs drove the claim**, by leave-one-out: run the step again with one input hidden and measure how much the claim changes;
- **whether the evidence was still valid** on the run date, by checking document versions and SUPERSEDES edges;
- **where the run first went wrong**, and the path from the stale evidence to the final decision;
- **what the decision becomes when the run is replayed** with current versions. The replay is a fork from the step where the stale evidence entered;
- **how stable the decision is**: the decision step is sampled 10 times at temperature 0.7 and the outcomes are counted.

Runs can also **pause at meaning-based breakpoints**, for example when a replaced policy enters the context. A reviewer can then approve, edit (fork with swapped evidence) or reject the run.

The demo uses a synthetic KYC onboarding workflow at the fictional **Harborline Bank**. All data is synthetic. In the main case, run **KYC-2041** for **Meridian Ledger LLC** retrieves **EDD Policy v3 §2.1**, which was retired on 1 Jul 2026. That makes the run 106 days out of date on 15 Oct 2026, and the run approves the account. A replay with v4 escalates it instead.

## 2. Tech constraints

- **Backend engine (`backend/supersede/`): Python standard library only.** It uses `sqlite3`, `json`, `re`, `math`, `difflib`, `uuid`, `dataclasses`, `urllib`, `threading`, `contextlib`, `copy`, `time`, `datetime`, `pathlib`, `collections`, `typing` and `os`. Python 3.10 or newer, with `from __future__ import annotations` in every module.
- **HTTP API:** FastAPI + uvicorn (`backend/api/app.py`), plus a fallback server written on the standard library only (`backend/api/stdlib_server.py`) that serves the same routes.
- **No LangChain, LangGraph or LangSmith.** The runtime, checkpoints, breakpoints and forks are all hand-written.
- **Frontend:** React 18 + TypeScript + Vite 8 (Node.js 20.19+ or 22.12+), styled with plain CSS in a single file. No router, UI, charting, graph or CSS libraries. The graph is absolutely positioned HTML nodes with SVG edges.
- **Tests:** `unittest` (standard library only).
- **Dev machine:** Windows. Smart App Control blocks unsigned `.exe` launchers, so run tools as `python -m pip`, `python -m uvicorn` and `python -m unittest`. Install into the main Python, not a virtual environment.
- **Encoding:** every file is UTF-8. Labels use the `§` character.

## 3. Repository layout

```
agent_rca/
  .gitignore                     # __pycache__/ *.pyc .venv/ backend/*.db frontend/node_modules/ frontend/dist/ .DS_Store
  CLAUDE.md                      # product + design decisions (not code; keep as is)
  README.md                      # run instructions, demo script, "how it works" table
  docs/
    REBUILD_SPEC.md              # this file
    observability-gaps.md        # original notes (not code)
  Supersede Decision Provenance for AI Agents.docx / .md   # concept documents (not code)
  design/
    v1/{Main,Answer,Graph,Replay,Audit,Hero}.dc.html       # superseded designs (reference only)
    v2/{V2-Overview,V2-Decision}.dc.html                   # current designs (reference only)
  backend/
    README.md
    requirements.txt             # "fastapi" and "uvicorn", unpinned, with a 2-line comment
    api/
      __init__.py                # empty
      app.py                     # FastAPI app
      stdlib_server.py           # same routes, standard library only
    supersede/
      __init__.py                # package docstring listing the layers; __version__ = "0.1.0"
      util.py
      store.py
      knowledge.py
      llm.py
      tracing.py
      runtime.py
      rules.py
      provenance.py
      service.py
      demo/
        __init__.py              # docstring: "Synthetic demo workflows. All names and data are fictional."
        kyc.py
        data/knowledge.json
        data/customers.json
    tests/
      test_engine.py
  frontend/
    README.md
    package.json  tsconfig.json  vite.config.ts  index.html
    src/
      main.tsx  App.tsx  router.ts  api.ts  types.ts  format.ts  layout.ts  styles.css
      components/Header.tsx  EvidenceGraph.tsx  Panels.tsx  StateDrawer.tsx
      pages/Overview.tsx  Decision.tsx
```

All commands run from `backend/`, which makes `supersede` and `api` importable as top-level packages. There is no `tests/__init__.py`.

## 4. Shared vocabulary

| Concept | Values |
|---|---|
| Run status | `running`, `paused`, `completed`, `rejected`, `forked` (a parent whose paused step was edited into a fork) |
| Span kind | `invoke_agent` (one per step), `chat`, `retrieval`, `execute_tool` |
| Chunk version status on a day | `current`, `retired`, `not_yet_effective` |
| Claim status | `current`, `replaced`, `nosource` |
| Graph-only status | `not_retrieved`: the current version of a retired chunk, which the agent never saw. `swapped_out`: in a fork, the old version that the fork's swap replaced |
| Claim kind | `claim`, `decision` |
| Event kind | `breakpoint`, `resumed`, `forked`, `blocked`, `rejected` |
| Finding | `healthy`, `unsourced`, `retired_in_context`, `claim_used_replaced`, `decision_used_replaced`, `outcome_unchanged`, `confirmed_by_replay` |
| Feedback verdict | `correct`, `wrong`, `needs_review` |
| Decision value | `approve`, `escalate`, `refer` |

**Id formats**

- Chunk: `"{doc_id}@v{version}#{section}"`, for example `edd-policy@v3#2.1`.
- Evidence item from a chunk: `"ev:{chunk_id}"`. Evidence item from a tool: `"ev:tool:{tool_name}"`.
- Claims: `c1` to `c5`, plus `decision`.
- Generated ids: `new_id(prefix)` returns `"{prefix}_{8 hex}"` (`run_…`, `span_…`, `evt_…`, `fb_…`, `KYC_…`).
- Demo run ids are fixed: `KYC-2041`, `KYC-2040`, `KYC-2039`, `KYC-2036`, `KYC-2033`.

**Dates**

- Business dates are `YYYY-MM-DD` strings.
- Timestamps are UTC ISO strings to whole seconds, for example `2026-10-15T10:42:00+00:00`.
- Display format is `"{day} {Mon} {year}"` with no zero-padding, for example `1 Jul 2026`.

---

## 5. Data model

### 5.1 SQLite schema (`store.py`, constant `SCHEMA`; use it word for word)

```sql
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    workflow TEXT NOT NULL,
    subject TEXT NOT NULL,
    status TEXT NOT NULL,              -- running | paused | completed | rejected
    run_time TEXT NOT NULL,            -- the business date the run acts on
    parent_run_id TEXT,
    forked_at INTEGER,                 -- step the fork restarted from
    fork_reason TEXT,
    paused_at INTEGER,
    pause_reason TEXT,
    options_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS spans (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    step INTEGER NOT NULL,
    agent TEXT NOT NULL,
    kind TEXT NOT NULL,                -- invoke_agent | chat | retrieval | execute_tool
    name TEXT NOT NULL,
    input_json TEXT,
    output_json TEXT,
    chunk_ids TEXT,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    started REAL NOT NULL,
    ended REAL NOT NULL,
    error TEXT,
    cached INTEGER NOT NULL DEFAULT 0  -- 1 = copied from the parent run by a fork
);
CREATE INDEX IF NOT EXISTS spans_run ON spans(run_id, step);
CREATE TABLE IF NOT EXISTS checkpoints (
    run_id TEXT NOT NULL,
    step INTEGER NOT NULL,             -- state AFTER this step (0 = initial state)
    state_json TEXT NOT NULL,
    PRIMARY KEY (run_id, step)
);
CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, verdict TEXT NOT NULL,  -- correct | wrong | needs_review
    note TEXT, author TEXT, at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, step INTEGER,
    kind TEXT NOT NULL,                -- breakpoint | resumed | forked | blocked | rejected
    detail_json TEXT NOT NULL, at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analyses (
    run_id TEXT PRIMARY KEY, report_json TEXT NOT NULL, at TEXT NOT NULL
);
```

(In the real file, the `feedback`, `events` and `analyses` tables put one column per line, like the tables above them.)

### 5.2 Run `options` (stored as `options_json`)

| Key | Meaning |
|---|---|
| `breakpoints: bool` | Default **true** when absent. False skips every rule. |
| `rules: {rule_key: bool}` | Turns individual rules on or off. If a key is absent, the rule's `default_on` applies. |
| `ack: ["rule@step", ...]` | Breakpoints already approved. They are skipped when the run resumes. |
| `swaps: {old_chunk_id: new_chunk_id}` | Evidence edits applied at retrieval time. Used by forks and replays. |
| `guard: bool` | Guard mode: any retired chunk is replaced by its current version at retrieval, and a `blocked` event is logged. |
| `model_call_limit: int` | Limit for the budget rule. Default 40. |

### 5.3 Agent state (a checkpoint's JSON)

```json
{
  "inputs":   { "name": "...", "business_type": "...", "business_label": "...", "base_risk": 22,
                "beneficial_owners": ["..."], "registry_match": true },
  "evidence": { "<ev id>": EvidenceItem },
  "claims":   { "<claim id>": Claim },
  "messages": [ { "from": "Document agent", "to": "Decision agent", "step": 2, "claim_ids": ["c1","c2"] } ],
  "scratch":  { "<agent>": { "<key>": "<any>" } },
  "decision": null | { "value": "approve", "text": "..." }
}
```

- **Chunk `EvidenceItem`:** `{id, kind:"chunk", chunk_id, doc_id, label, text, score, step, agent}`.
- **Tool `EvidenceItem`:** `{id, kind:"tool", label, text (JSON of result, ensure_ascii False), result, step, agent}`.
- **`Claim`:** `{id, text, agent, step, inputs: [ids in context], value, kind}`.

Checkpoint 0 is the initial state. Checkpoint *n* is the state after step *n*.

---

## 6. Demo data (copy these files exactly)

### 6.1 `backend/supersede/demo/data/knowledge.json`

```json
{
  "chunks": [
    {
      "id": "edd-policy@v3#2.1", "doc_id": "edd-policy", "title": "EDD Policy", "section": "2.1", "version": 3,
      "effective_on": "2026-01-01", "retired_on": "2026-07-01", "owner": "Financial Crimes Compliance",
      "text": "Enhanced due diligence escalation list. Escalate to EDD: money services businesses, casinos and dealers in precious metals. Business types not on this escalation list follow standard onboarding."
    },
    {
      "id": "edd-policy@v4#2.1", "doc_id": "edd-policy", "title": "EDD Policy", "section": "2.1", "version": 4,
      "effective_on": "2026-07-01", "retired_on": null, "owner": "Financial Crimes Compliance",
      "text": "Amended July 2026. Escalate to EDD: money services businesses, casinos, dealers in precious metals and virtual asset service providers, including custody and exchange businesses."
    },
    {
      "id": "risk-guide@v2#1", "doc_id": "risk-guide", "title": "Risk Rating Guide", "section": "1", "version": 2,
      "effective_on": "2025-10-01", "retired_on": null, "owner": "Enterprise Risk",
      "text": "Score customer risk from 0 to 100. Bands: 0 to 39 low, 40 to 69 medium, 70 to 100 high. Business types on the EDD escalation list score at least 70."
    },
    {
      "id": "kyc-procedure@v5#3", "doc_id": "kyc-procedure", "title": "KYC Procedure", "section": "3", "version": 5,
      "effective_on": "2026-02-01", "retired_on": null, "owner": "Operations",
      "text": "Standard onboarding: verify registration documents against the state business registry and screen every beneficial owner against sanctions lists."
    }
  ],
  "supersedes": [
    {"new": "edd-policy@v4#2.1", "old": "edd-policy@v3#2.1"}
  ]
}
```

The v3 text deliberately repeats the query words ("escalation list", "business types", "standard onboarding"). That makes plain BM25 rank v3 first, and v4 does not reach the top 2. This is the bug the demo exposes.

### 6.2 `backend/supersede/demo/data/customers.json`

The file is an array of five objects, in this order. Every object has these keys: `run_id, name, business_type, business_label, base_risk, beneficial_owners, registry_match, run_time, created_at, options`. Some also have `note`.

| run_id | name | business_type | business_label | base_risk | beneficial_owners | run_time | created_at | options |
|---|---|---|---|---|---|---|---|---|
| KYC-2041 | Meridian Ledger LLC | digital asset custody | Digital asset custody | 22 | Dana Whitlow, Arun Mehta | 2026-10-15 | 2026-10-15T10:42:00+00:00 | `{"breakpoints": false}` |
| KYC-2040 | Bluefin Logistics Inc. | freight forwarding | Freight forwarding | 18 | Marisol Ortega | 2026-10-15 | 2026-10-15T10:15:00+00:00 | `{"breakpoints": false}` |
| KYC-2039 | Okafor & Reyes Dental | healthcare practice | Healthcare practice | 31 | Chidi Okafor, Lucia Reyes | 2026-10-15 | 2026-10-15T09:41:00+00:00 | `{"breakpoints": false}` |
| KYC-2036 | Tidewater Coin Exchange | virtual asset exchange | Virtual asset exchange | 26 | Hollis Brandt, Mei Tanaka | 2026-10-14 | 2026-10-14T16:20:00+00:00 | `{"breakpoints": true}` |
| KYC-2033 | Granite Peak Builders | construction | Construction | 20 | Owen Gallagher | 2026-10-14 | 2026-10-14T14:02:00+00:00 | `{"breakpoints": false}` |

`registry_match` is `true` for all five.

Notes:
- KYC-2041: `"Historical run, recorded before breakpoints were switched on. The demo's main case."`
- KYC-2036: `"Run with breakpoints on: pauses when the retired policy enters the context."`

---

## 7. Backend modules

### 7.1 `util.py`

| Function | Behaviour |
|---|---|
| `new_id(prefix)` | Returns `f"{prefix}_{uuid.uuid4().hex[:8]}"`. |
| `now_iso()` | Returns `datetime.now(timezone.utc).isoformat(timespec="seconds")`. |
| `parse_day(value)` | Returns `None` if the value is falsy. Otherwise returns `date.fromisoformat(value[:10])`. |
| `tokens(text)` | Returns `re.findall(r"[a-z0-9]+", text.lower())`. |
| `similarity(a, b)` | Returns 1.0 if `a == b`. Otherwise returns `difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()`. |
| `rough_token_count(text)` | Returns `max(1, len(text) // 4)`. |

### 7.2 `store.py`

- `_dumps(v)` is `json.dumps(v, ensure_ascii=False, sort_keys=True, default=str)`.
- `class Store` is an interface whose methods have `...` bodies:

  ```
  create_run, update_run(run_id, **fields), get_run, list_runs, add_span, spans,
  save_checkpoint(run_id, step, state), checkpoint(run_id, step), checkpoints(run_id) -> [(step, state)],
  add_feedback, feedback, add_event, events, save_analysis(run_id, report, at), analysis, children, clear
  ```

`class SQLiteStore(Store)` works as follows:

- **Constructor:** `__init__(path="supersede.db")`. Path `":memory:"` is used by the tests. It sets up `threading.RLock`, `sqlite3.connect(path, check_same_thread=False)` and `row_factory = sqlite3.Row`, then runs `executescript(SCHEMA)` and commits.
- **Helpers:** `_exec(sql, params)` runs and commits under the lock. `_all(sql, params)` returns a list of dicts.
- **`create_run(run)`:** the key `options` is popped and stored as `options_json`. The insert is built from the dict's keys.
- **`update_run`:** a no-op when no fields are given. `options` is re-serialised to `options_json`. It runs `UPDATE runs SET k = ? ... WHERE id = ?`.
- **Reading runs:** run rows come back with `options` (parsed) in place of `options_json`. `list_runs` orders by `created_at DESC, id`. `children(run_id)` returns runs with that `parent_run_id`, ordered by `created_at`.
- **Spans:** `add_span` pops `input`, `output` and `chunk_ids` into JSON columns. `spans(run_id)` orders by `step, started` and decodes `input`, `output` and `chunk_ids` back.
- **Checkpoints and analyses:** both use `INSERT OR REPLACE`. `checkpoint` returns the parsed state or `None`. `checkpoints` is ordered by step.
- **Events:** `add_event` pops `detail` into `detail_json`. `events` orders by `at, id` and decodes `detail`. `feedback(run_id)` orders by `at`.
- **`clear()`:** deletes all rows from runs, spans, checkpoints, feedback, events and analyses.

### 7.3 `knowledge.py`

`@dataclass Chunk` has these fields:

```
id, doc_id, title, section, version: int, text, effective_on, retired_on=None, owner="", kind="document", meta=dict
```

- Property `label` returns `f"{title} v{version} §{section}"`, for example `EDD Policy v3 §2.1`.
- `to_dict()` returns `asdict` plus `label`.

`class KnowledgeBase(chunks, supersedes=[(new, old)])`:

- **Edges:** `replaces[new] = old` and `replaced_by[old] = new`. `add_supersedes` raises `KeyError("unknown chunk in SUPERSEDES edge …")` if either id is unknown.
- **Loading:** `from_json(path)` reads `{"chunks": [...], "supersedes": [{"new","old"}]}`.
- **`get(id)`:** returns the chunk.
- **`status_on(id, day)`:** `day` may be a str or a date. Returns `not_yet_effective` if `effective_on > day`. Returns `retired` if `retired_on` is set and `retired_on <= day`. Otherwise returns `current`.
- **`days_out_of_date(id, day)`:** returns `max(0, (day - retired_on).days)` if the chunk is retired, else 0.
- **`current_version(id, day)`:** while the chunk is `retired` on that day and has a `replaced_by` entry, move to that entry. Stops on cycles (it tracks a seen set).
- **Index:** built at construction. Term frequencies are counted over `tokens(title + " " + text)`. Document length is the sum of term frequencies, and `avg` is the mean length. `idf[t] = log(1 + (n - df + 0.5) / (df + 0.5))`.
- **`search(query, top_k=3, doc_ids=None)`:** plain BM25 with `k1 = 1.4` and `b = 0.75`, and **no version awareness**. It only scores chunks whose `doc_id` is in `doc_ids`, if that is given. For each query token: `s += idf * f * (k1+1) / (f + k1*(1 - b + b*len/avg))`. Only results with `s > 0` are kept, with the score rounded to 4 decimals. Results sort by `(-score, id)`, cut to `top_k`, and come back as `[(chunk_id, score)]`.
- **`retrieve(query, *, top_k=3, doc_ids=None, swaps=None, guard_day=None)`:** looks at each search hit in turn:
  - if `swaps` contains the hit, use the mapped id and record `{"from", "to"}` in `swapped`;
  - otherwise, if `guard_day` is set and the hit is retired on that day, use `current_version` and record it in `blocked`;
  - then add `{"id": final, "score": original_score}` unless `final` is already in the output.

  It returns `{"chunks": [...], "swapped": [...], "blocked": [...]}`.

### 7.4 `llm.py`

- `@dataclass LLMResponse(text, tokens_in, tokens_out, model)`.
- `class LLMClient(Protocol)` has `complete(messages, *, purpose, temperature=0.0, sample=0) -> LLMResponse`.
- `Script = Callable[[str, list[dict], int], str]`, meaning `(purpose, messages, sample) -> text`.
- **`MockLLMClient(script)`:**
  - `model = "mock-1"`. A `calls` counter goes up on every call.
  - Text comes from `script(purpose, messages, sample if temperature > 0 else 0)`.
  - `tokens_in` is `rough_token_count` of all the message contents joined with spaces. `tokens_out` is `rough_token_count(text)`.
- **`AzureOpenAIClient(endpoint=None, key=None, deployment=None, api_version=None, timeout=60)`:**
  - Reads the env vars `AZURE_OPENAI_ENDPOINT` (trailing `/` stripped), `AZURE_OPENAI_KEY`, `AZURE_OPENAI_DEPLOYMENT` and `AZURE_OPENAI_API_VERSION` (default `2024-06-01`). `model = deployment`.
  - Sends `POST {endpoint}/openai/deployments/{deployment}/chat/completions?api-version={v}` using `urllib.request`. Headers are `Content-Type: application/json` and `api-key`. The body is `{"messages", "temperature"}`.
  - Returns `choices[0].message.content.strip()`, with token counts from `usage.prompt_tokens` and `usage.completion_tokens` and the model from `data.model`.

### 7.5 `tracing.py`

- **`SpanHandle`:** mutable fields `output=None`, `chunk_ids=[]`, `tokens_in=0`, `tokens_out=0`, `error=None` and `simulated_seconds=None`. When `simulated_seconds` is `None`, the measured time is used.
- **`Tracer(store | None, run_id)`:**
  - `store=None` makes a silent tracer, used for sandboxed re-runs.
  - It keeps `model_calls = 0` and a virtual clock `_clock = time.time()`.
- **`span(*, step, agent, kind, name, input=None)`** is a context manager that yields a handle:
  - On entry: `wall = max(time.time(), _clock)`, and measurement starts with `perf_counter`.
  - Exceptions are recorded as `"{Type}: {msg}"` in `error` and re-raised.
  - On exit, even after an error: `elapsed` is the simulated time if set, otherwise the measured time. `_clock` becomes `wall + elapsed`. If `kind == "chat"`, `model_calls` goes up by 1. Then, if there is a store, it adds a span row: `{id: new_id("span"), run_id, step, agent, kind, name, input, output, chunk_ids, tokens_in, tokens_out, started: wall, ended: wall + elapsed, error, cached: 0}`.

  The virtual clock is what lets the mock produce realistic, sequential durations.

### 7.6 `runtime.py`

- **`@dataclass Step(name, label, agent, fn: Callable[[StepContext], None], irreversible=False)`.**
- **`@dataclass Workflow(name, steps)`:** `step(n)` returns `steps[n-1]` (steps are numbered from 1). `size` is `len(steps)`.
- **`initial_state(inputs)`:** returns `{"inputs": inputs, "evidence": {}, "claims": {}, "messages": [], "scratch": {}, "decision": None}`.
- **`@dataclass Pause(rule, step, message, detail=dict)`.**
- `estimate_tokens(text)` is an alias of `rough_token_count`.

#### StepContext

Constructor: `StepContext(*, state, step_no, step, kb, llm, tracer, run, exclude=None, temperature=0.0, sample=0)`. It sets `options = run.get("options", {})`, `exclude` (a set, used for leave-one-out) and `events = []`. The property `agent` returns `step.agent`.

- **`retrieve(query, *, top_k=2, doc_ids=None)`**
  - Calls `kb.retrieve` with `swaps = options.get("swaps", {})` and `guard_day = run["run_time"]` if `options.get("guard")`.
  - Runs inside a span: kind `retrieval`, name `knowledge.search`, input `{"query", "top_k"}`.
  - For every result chunk it builds the chunk evidence item and **always** writes it into `state["evidence"]`. It returns only the items whose id is **not** in `exclude`.
  - Span `chunk_ids` is the list of final ids. Output is `{"chunks": ids, "swapped", "blocked"}`. Simulated time 0.18 s.
  - Each `blocked` entry adds `{"kind": "blocked", "detail": {"step": step_no, "from", "to"}}` to `ctx.events`.
- **`tool(tool_name, fn, *, label, **args)`**
  - Runs inside a span: kind `execute_tool`, name `tool_name`, input `args`. Output is `fn(**args)`. Simulated time 0.35 s.
  - The evidence item `ev:tool:{tool_name}` is always stored. The method returns `None` if that id is in `exclude`.
- **`upstream_claims(ids)`:** returns the claims that exist and are not excluded, in the order given.
- **`chat(purpose, system, user)`**
  - Messages are `[{"role": "system", "content": system}, {"role": "user", "content": user}]`.
  - Runs inside a span: kind `chat`, name `purpose`, input `{"messages"}`.
  - Calls `llm.complete(messages, purpose=, temperature=self.temperature, sample=self.sample)`.
  - Span output is `{"text", "model"}`, plus the token counts. If the model name starts with `"mock"`, simulated time is `round(0.6 + tokens_out*0.02 + tokens_in*0.002, 2)`.
  - Returns the text.
- **`claim(claim_id, text, *, inputs, value=None, kind="claim")`:** stores `{id, text, agent, step, inputs, value, kind}`. The `inputs` list holds everything that was in context. Leave-one-out decides later which inputs drove the claim.
- **`handoff(to_agent, claim_ids)`:** appends a message to `state["messages"]`.
- **`decide(value, text, *, inputs)`:** stores a claim with id `"decision"` and `kind="decision"`, and sets `state["decision"] = {"value", "text"}`.
- **`note(key, value)`:** sets `state["scratch"][agent][key]`.

#### Runner

Constructor: `Runner(store, kb, llm, workflow, rules=None)`.

**`start(*, subject, inputs, run_time, options=None, run_id=None, created_at=None)`**

- Creates the run with status `running`. All the parent, fork and pause fields are `None`. `created_at` defaults to `now_iso()`.
- Saves checkpoint 0 as `initial_state(inputs)`, then calls `_run_from(id, 1)`. Returns the id.

**`resume(run_id, action, *, swaps=None, note="")`**

- Raises `ValueError(f"run {id} is {status}, not paused")` if the run is not paused. Otherwise `step = paused_at`, and `rule` is the rule whose key is `pause_reason`.
- `approve`:
  - Appends `"{pause_reason}@{step}"` to `options.ack`.
  - Sets status `running` and `paused_at` to `None`. `pause_reason` is kept.
  - Logs a `resumed` event `{"action": "approve", "note"}`.
  - Continues with `_run_from(step if rule.when == "before" else step + 1)`.
  - Returns the same id.
- `reject`: sets status `rejected`, logs a `rejected` event `{"note"}`, and returns the same id.
- `edit`: calls `fork(run_id, from_step=step, swaps=swaps or {}, reason="edited at breakpoint")`, sets the **parent's** status to `forked`, and returns the new id.
- Any other action raises `ValueError(f"unknown action {action!r}")`.

**`fork(run_id, *, from_step, swaps=None, options=None, reason="fork", run_new_id=None)`**

1. Raises `ValueError("from_step out of range")` unless `1 <= from_step <= size`.
2. Child options: deep-copy the parent's options, remove `ack`, set `swaps` to the parent's swaps merged with the new `swaps`, then `update(options)`.
   - **Reuse identical forks.** If the parent already has a child with the same `forked_at` and exactly these options, and no `run_new_id` was given, return that child's id and stop. With the mock model an identical fork would produce exactly the same run. This also makes a "Fork with the current version" click return the automatic replay.
3. Create the child run with the same workflow, subject and run_time, `parent_run_id=run_id`, `forked_at=from_step`, `fork_reason=reason` and `created_at=now_iso()`.
4. Copy the parent's checkpoints with `step < from_step` (checkpoint 0 included).
5. Copy the parent's spans with `step < from_step`, each with a new id, the child's `run_id` and `cached=1`.
6. Log a `forked` event **on the parent** at `from_step`, with detail `{"child", "swaps", "reason"}`.
7. Call `_run_from(child, from_step)` and return the child id.

**`rerun_step(run, step_no, *, exclude=None, temperature=0.0, sample=0, state=None)`**

A sandboxed re-run of one step. It deep-copies `state`, or the run's checkpoint at `step_no - 1` if no state is given. It runs the step with a silent `Tracer(None, ...)`, stores nothing, and returns the resulting state.

**`_run_from(run_id, start)`**

1. Create a new `Tracer(store, run_id)`. Set its `model_calls` to the number of existing `chat` spans, cached ones included.
2. For each `step_no` from `start` to `size`:
   1. Reload the run row. Deep-copy checkpoint `step_no - 1` as `state`.
   2. Check the `before` rules with `(before=state, after=state)`. On a hit, call `_pause` and return.
   3. Build a `StepContext`. Set `t0 = max(time.time(), tracer._clock)`.
   4. Run `step.fn(ctx)` inside an `invoke_agent` span named `step.name`, with input `{"label"}`. The span output is `{"claims": [ids of claims whose step == step_no]}`. Its simulated time is `max(0, tracer._clock - t0)`, so the agent span lasts as long as the calls inside it.
   5. Save checkpoint `step_no`, and log each entry of `ctx.events` as an event.
   6. Check the `after` rules with `(before=checkpoint(step_no - 1), after=ctx.state)`. On a hit, pause and return.
3. When the loop finishes, set status `completed` and `paused_at` to `None`.

**`_check(run, when, step_no, before, after, tracer)`**

- Returns `None` if `options.get("breakpoints", True)` is false.
- Otherwise, for each rule in order:
  - skip it unless `rule.when == when` and `options.rules.get(key, rule.default_on)` is true;
  - skip it if `"{key}@{step_no}"` is in `ack`;
  - otherwise call `rule.check(run=, step_no=, step=workflow.step(step_no), before=, after=, kb=, store=, tracer=)`.
- Returns the first hit.

**`_pause(run_id, pause)`:** sets status `paused`, `paused_at=pause.step` and `pause_reason=pause.rule`. Logs a `breakpoint` event with detail `{"rule", "message", **pause.detail}`.

**`_event(run_id, step, kind, detail)`:** adds an event row `{id: new_id("evt"), run_id, step, kind, detail, at: now_iso()}`.

### 7.7 `rules.py`

This module imports `Pause` from runtime. `_fmt(day)` formats a date as `"1 Jul 2026"`.

Base class `Rule` has class attributes `key`, `label`, `when="after"` and `default_on=True`, an abstract `check(**kw)`, and `describe()`, which returns `{key, label, when, default_on}`. Every `check` accepts keyword arguments and ignores the ones it doesn't use (`**_`).

| Class | key | label | when | default_on | Fires when | message |
|---|---|---|---|---|---|---|
| `StaleEvidenceRule` | `stale_evidence` | `A replaced source enters the context` | after | yes | A chunk evidence id that is in `after.evidence` but not in `before.evidence` is `retired` on `run_time` | `f"The {step.agent} retrieved {chunk.label}, which was replaced on {_fmt(retired_on)}."` |
| `ToolLoopRule` (threshold 3) | `tool_loop` | `The same tool runs 3 or more times` | after | yes | Across all of the run's `execute_tool` spans, some span has 3 or more spans with the same name whose `similarity(json.dumps(input, sort_keys=True), …) >= 0.9`, itself included | `f"Tool {name} ran {n} times with near-identical arguments."` |
| `UngroundedBeforeActionRule` | `ungrounded_before_action` | `An unsupported claim precedes an account decision` | before | yes | `step.irreversible` is true and some claim with `kind == "claim"` in `before.claims` has empty `inputs` | see below |
| `BudgetRule` (limit 40) | `budget` | `The run passes 40 model calls` | after | **no** | `tracer.model_calls > options.get("model_call_limit", 40)` | `f"{calls} model calls, over the limit of {limit}."` |

Hit details:
- `stale_evidence`: `{"chunk_id", "current_id", "retired_on", "days_out_of_date", "suggested_swaps": {chunk_id: current_id}}`.
- `tool_loop`: `{"tool", "count"}`.
- `ungrounded_before_action`: `{"claim_ids"}`.
- `budget`: `{"model_calls", "limit"}`.

The ungrounded message is built like this:
1. Turn each id into a name: `"claim 05"` (the number after `c`, zero-padded to 2 digits), or the raw id if it isn't `c<digits>`.
2. Join the names with `", "` and capitalise the first letter.
3. Use the verb `has` for one claim and `have` for several.
4. The message is `f"{Names} {verb} no source in the agent's context, and the next step ({step.label.lower()}) cannot be undone."`. Example: `Claim 05 has no source in the agent's context, and the next step (decide) cannot be undone.`

`default_rules()` returns `[StaleEvidenceRule(), ToolLoopRule(), UngroundedBeforeActionRule(), BudgetRule()]`. The order matters.

### 7.8 `demo/kyc.py`

Constants:
- `DATA = Path(__file__).parent / "data"`
- `VASP_TYPES = {"digital asset custody", "virtual asset exchange"}`
- `CLASSIC_EDD_TYPES = {"money services business", "casino", "precious metals dealer"}`

Fake tools:
- `registry_lookup(name, match)` returns `{"registered_name": name if match else name + " Holdings", "status": "active", "match": match}`.
- `sanctions_screen(owners)` returns `{"screened": len(owners), "matches": 0, "lists": ["OFAC SDN", "UN consolidated"]}`.

`SYSTEM = "You are a KYC onboarding agent at a bank. Answer in one sentence, using only the evidence given."`

The prompts use labelled lines (`NAME: value`), so both the mock and a real model can read them. `inp` means `ctx.state["inputs"]`.

| # | Step(name, label, agent) | Body |
|---|---|---|
| 1 | `parse_documents`, "Parse documents", "Document agent" | `ev = ctx.tool("registry_lookup", registry_lookup, label="State business registry", name=inp.name, match=inp.registry_match)`. User prompt: `CUSTOMER: {name}\nREGISTRY: {ev.text or 'unavailable'}\nTask: do the registration documents match the registry?`. Chat purpose `verify_registration`. Claim `c1` with inputs `[ev.id]` (or `[]`). |
| 2 | `sanctions_check`, "Sanctions check", "Document agent" | `ctx.tool("sanctions_screen", sanctions_screen, label="Sanctions screening", owners=inp.beneficial_owners)`. User prompt: `OWNERS: {', '.join(owners)}\nSCREENING: {ev.text or 'unavailable'}\nTask: summarise the sanctions screening.`. Purpose `sanctions_summary`. Claim `c2`. Then `handoff("Decision agent", ["c1", "c2"])`. |
| 3 | `retrieve_edd`, "Retrieve EDD policy", "Risk agent" | `chunks = ctx.retrieve("enhanced due diligence escalation list business types standard onboarding", top_k=2, doc_ids=["edd-policy", "risk-guide"])`. `policy` is the chunks with `doc_id == "edd-policy"`. Each becomes a line `POLICY [{label}]: {text}`, or the single line `POLICY: none retrieved`. User prompt: `BUSINESS: {business_type}\n{lines}\nTask: is this business type on the EDD escalation list?`. Purpose `classify_edd`. Claim `c3` with inputs = all chunk ids. Then `note("retrieved", [labels])`. |
| 4 | `score_risk`, "Score risk", "Risk agent" | `finding = upstream_claims(["c3"])`. `guide` is the state evidence with `doc_id == "risk-guide"` that is not excluded. User prompt: `BUSINESS: …\nBASE_RISK: {base_risk}\nEDD_FINDING: {finding[0].text or 'none'}\nRISK_GUIDE: {guide[0].text or 'none'}\nTask: give a risk score from 0 to 100.`. Purpose `score_risk`. The value is the number in `(\d+) of 100`, or None. Claim `c4` with inputs = finding ids + guide ids, and that value. Then `handoff("Decision agent", ["c3", "c4"])`. |
| 5 | `check_volume`, "Check volume", "Decision agent" | User prompt: `CUSTOMER: …\nBUSINESS: …\nTask: does the expected monthly volume fit the business size?`. Purpose `check_volume`. Claim `c5` with **inputs `[]`** (ungrounded on purpose). |
| 6 | `decide`, "Decide", "Decision agent", **irreversible=True** | `claims = upstream_claims(["c1", …, "c5"])`. User prompt: one line `CLAIM {id}: {text}` per claim, then `\nTask: approve the account, or escalate it to enhanced due diligence?`. Purpose `decide`. Value: `escalate` if the lowercased text contains "escalate", else `approve` if it contains "approve", else `refer`. Then `ctx.decide(value, text, inputs=[claim ids])`. |

`workflow()` returns `Workflow("kyc_onboarding", [the six steps above])`.

**`mock_script(purpose, messages, sample)`** is deterministic and reads `user = messages[-1]["content"]`. `_field(user, NAME)` returns the stripped value of the line matching `^NAME: (.*)$` (multiline), or `""`.

- **`verify_registration`:** if `REGISTRY` is `unavailable`, return `"Registration could not be verified against the registry."`. Otherwise parse it as JSON. If `match` is true, return `"Registration documents match the state business registry."`, else `"Registration details do not match the state business registry."`.
- **`sanctions_summary`:** if `SCREENING` is `unavailable`, return `"Sanctions screening results are unavailable."`. Otherwise take `n = screened`. The opening words are `"One beneficial owner was"`, `"Two beneficial owners were"` or `"Three beneficial owners were"` for 1 to 3, else `f"{n} beneficial owners were"`. Return `f"{word} screened against sanctions lists with no matches."`.
- **`classify_edd`:**
  - `business = BUSINESS`, `label = business.capitalize()`, and `policies = re.findall(r"^POLICY \[(.*?)\]: (.*)$", user, re.M)`.
  - If there are no policies, return `f"No EDD escalation rule was found for {business}."`.
  - For each `(name, text)` with `t = text.lower()`:
    - if business is in `VASP_TYPES` and `"virtual asset"` is in `t`, return `f"{label} is a virtual asset service provider, which requires EDD under {name}."`;
    - if business is in `CLASSIC_EDD_TYPES` and `business.split()[0]` is in `t`, return `f"{label} is on the EDD escalation list under {name}."`.
  - Otherwise return `f"{label} is not on the EDD escalation list."`.
- **`score_risk`:**
  - `base = int(BASE_RISK or 30)`.
  - The score is 45 if `EDD_FINDING == "none"`. It is `max(71, base + 45)` if the finding (lowercased) contains `"requires edd"` or `"on the edd escalation list under"`. Otherwise it is `base`.
  - If `RISK_GUIDE == "none"`, return `f"Risk score {score} of 100."`.
  - Otherwise the band is `low` (below 40), `medium` (below 70) or `high`. The tail is `"so no enhanced due diligence is needed"`, `"so a manual review is advised"` or `"so enhanced due diligence is required"`. Return `f"Risk score {score} of 100 ({band}), {tail}."`.
- **`check_volume`:** return `"Expected monthly volume fits the stated business size."`.
- **`decide`:** let `m = re.search(r"Risk score (\d+) of 100", user)`.
  - If the lowercased user text contains `"requires edd"`, or `m` is found with a score of 40 or more, return `"Escalate to enhanced due diligence review."`.
  - If `m` is not found, return `"Refer to an analyst: the risk score is missing."`.
  - If `"monthly volume"` is in the user text and `sample % 10 >= 6`, return the escalate text. This is what gives 6 approve / 4 escalate over 10 samples.
  - Otherwise return `"Approve account. Low risk, no enhanced due diligence required."`.
- **Any other purpose:** return `"No answer."`.

Helpers:
- `knowledge()` returns `KnowledgeBase.from_json(DATA / "knowledge.json")`.
- `customers()` loads the customers JSON.
- `mock_llm()` returns `MockLLMClient(mock_script)`.
- `customer_inputs(c)` picks the keys `name, business_type, business_label, base_risk, beneficial_owners, registry_match`.

### 7.9 `provenance.py`

Constants:
- `DROVE_SHARE = 0.2`
- `MIN_CHANGE = 0.05`
- `REPLAY_REASON = "replay with current versions"`

`FINDINGS` maps each finding to its label. `confirmed_by_replay` and `decision_used_replaced` share a label.

| finding | label |
|---|---|
| healthy | All evidence current |
| unsourced | Claim without a source |
| retired_in_context | Retired source retrieved, not used |
| claim_used_replaced | A claim used a replaced source |
| decision_used_replaced | Decision used replaced policy |
| outcome_unchanged | Replaced source used, outcome unchanged |
| confirmed_by_replay | Decision used replaced policy |

`fmt_day(value)` returns `"1 Jul 2026"`, or `""` when there is no value.

**`state_diff(before | None, after)`**

When `before` is None it is treated as an empty state. The result has:
- for `evidence` and `claims`: `{added, changed, removed}` (lists of keys);
- `messages`: `{"added": after.messages[len(before.messages):]}`;
- `scratch`: the agents whose scratch differs, with their new values;
- `decision`: `after.decision` if it changed, else None.

#### `class Analyzer(runner)`

The analyzer uses `runner.store`, `runner.kb` and `runner.workflow`. `_last_step(run)` is the highest checkpoint step the run has.

**`attribute(run, state)`:** for every claim:

1. For each input, `raw[inp] = _change(run, claim, {inp})`.
2. **Pairwise fallback for redundant causes.** If the total is 0 and the claim has 2 to 6 inputs: for every pair (i, j), compute `ch = _change(run, claim, {i, j})`, then add `ch / 2` to both `raw[i]` and `raw[j]`. Round to 4 places and recompute the total.
3. `share[k] = round(raw[k] / total, 3)`, or 0 when the total is 0.
4. `drove` is the inputs with `share >= DROVE_SHARE` and `raw >= MIN_CHANGE`.

It returns `{cid: {"change": raw, "share": shares, "drove": [ids]}}`.

**`_change(run, claim, exclude)`:** re-runs the claim's step with `exclude` hidden.
- If the claim is missing from the result, return 1.0.
- If the claim is a decision and its `value` differs, return 1.0.
- Otherwise return `round(1 - similarity(old_text, new_text), 4)`.

**`supports(claim_text, evidence_text)`:** a cheap corroboration check.
1. Take the claim's words: lowercase, `.` replaced by a space, split.
2. Drop words of 2 letters or fewer, and stop words: the a an of to and is on in for with this so no not are be.
3. Return true if at least 2 of the remaining words appear in the evidence's word set, which is lowercased and split the same way.

**`analyze(run_id, *, replay=True, samples=10)`**

Raises `KeyError` if the run is unknown. It works on `last = _last_step(run)`, `state = checkpoint(last)` and `day = run_time`.

1. **Evidence validity.** Copy each evidence item.
   - Chunk items get `version_status = kb.status_on(chunk_id, day)`, plus `days_out_of_date`, `current_id = current_version(...)`, `current_label` and `retired_on`.
   - Tool items get `version_status = "current"`.
2. **Attribution.** Call `attribute(run, state)`.
3. **Claim status**, iterating claims sorted by `(step, id)` so that upstream claims are resolved first.
   - `via` = the driving inputs that are retired evidence or claims already marked `replaced`.
   - The status is `replaced` if `via` is non-empty. It is `nosource` if `kind == "claim"` and (the claim has no inputs, or none of them drove it). Otherwise it is `current`.
   - The output claim is `{**claim, status, replaced_via: via, attribution: [...], main_source}`.
   - `attribution` has one entry per input, in input order: `{"input", "share", "change", "drove", "supports"}`. `supports` is only computed for evidence inputs; claim inputs get None.
   - `main_source` is the input with the highest share if anything drove the claim, else None.
4. **Decision path.** A depth-first walk with a stack, starting at `"decision"` (if present). Pop a node and skip it if it is already in `path`; otherwise append it. If the node is a claim, push the inputs that drove it, in attribution order. The result `decision_path` is the list in visit order.
5. **Retired evidence.**
   - `retired` = evidence items whose status is `retired`.
   - `retired_driving` = the retired ids that appear in any claim's `replaced_via`.
   - `on_path` = the members of `retired_driving` that are also in `path`.
6. **Replay.** Call `_replay(run, state, retired, claims)` if `replay` is true, `retired` is non-empty, and the run status is `completed`, `paused` or `forked`.
7. **Finding**, decided in this order:
   - no retired evidence: `unsourced` if any claim is `nosource`, else `healthy`;
   - no `retired_driving`: `retired_in_context`;
   - no `on_path`: `claim_used_replaced`;
   - replay exists and the decision changed: `confirmed_by_replay`;
   - replay exists (decision unchanged): `outcome_unchanged`;
   - otherwise: `decision_used_replaced`.
8. **First wrong step.** Take the replaced claim with the lowest step. `entered` is the lowest step among its `replaced_via` items that are evidence, or the claim's own step if none are. The result is `{"step": entered, "agent": wf.step(entered).agent, "label": wf.step(entered).label}`, or None if no claim is replaced.
9. **Report.** Save it with `store.save_analysis` and return it:

   ```
   version (REPORT_VERSION = 2), run, analysed_at (now_iso), last_step, decision (state.decision), finding, finding_label,
   first_wrong_step, days_out_of_date (max over retired_driving evidence, else 0),
   evidence, claims, decision_path, replay, stability, steps, counts, graph, read
   ```

   - `stability` is `stability(run, samples)` if the claims include `decision` and `samples` is non-zero, else None.
   - `steps` is `step_table(run_id)`.
   - `graph` is `graph(report)` and `read` is `analyst_read(report)`.
   - `counts` has:

     | Key | Value |
     |---|---|
     | `claims` | number of claims with `kind == "claim"` |
     | `current` | those with status `current` |
     | `replaced` | those with status `replaced` |
     | `nosource` | all claims with status `nosource` |
     | `evidence` | `len(evidence)` |
     | `unused_evidence` | evidence ids that drove nothing |

**`_replay(run, state, retired, claims)`**

1. `swaps = {chunk_id: current_id}` for every retired item whose current version differs. Return None if `swaps` is empty.
2. `from_step` is the lowest step among the retired items.
3. Reuse an existing child of the run whose `fork_reason == REPLAY_REASON`. If there is none, create one with `runner.fork(run_id, from_step=, swaps=, options={"breakpoints": False}, reason=REPLAY_REASON)`.
4. Read the child's checkpoint at `wf.size`, or its latest checkpoint.
5. Return:

   ```
   {run_id, status, from_step, swaps, decision_before, decision_after,
    decision_changed (both not None and different), claims: diff}
   ```

   The diff has one entry per parent claim: `{"id", "before", "after" (or None), "changed": after exists and similarity < 0.98}`.

**`stability(run, samples=10)`**

1. The decision step is `claims["decision"]["step"]`, read from the latest checkpoint.
2. For each `i` in `range(samples)`, run `rerun_step(run, step, temperature=0.7, sample=i)` and count the decision `value`, using `"none"` if there is no decision.
3. Return `{"samples", "counts", "stable": top == samples, "agreement": round(top / samples, 2)}`, where `top` is the highest count.

**`step_table(run_id)`:** one row for each workflow step *i*, based on that step's spans:

```
{step, name, label, agent, irreversible,
 ran: an invoke_agent span exists,
 cached: that span's cached flag,
 seconds: round(ended - started, 2) of the agent span, or 0,
 tokens: sum of tokens_in + tokens_out over chat spans,
 model_calls, tool_calls, retrievals: counts by span kind}
```

**`graph(report)`**

- `agents` lists the step agents in order of first appearance. `columns = ["Evidence", *agents, "Outcome"]`.
- `weight[input]` = the highest `share` that input has on any claim it **drove** (0 otherwise).
- **Evidence nodes**, sorted by `(step, id)`:

  ```
  {id, type:"evidence", kind, label, text, column:0, step, agent,
   status: version_status, weight, on_path, retired_on, days_out_of_date,
   swapped_in: chunk_id is one of run.options.swaps' values}
  ```

  For each retired item that has a `current_id`, add a node `ev:{current_id}` (if it is not already evidence) with `status: "not_retrieved"`, `agent: None`, `weight: 0`, `on_path: False` and the same step. Add an edge `{from: that node, to: the retired item, type: "replaces", share: None, on_path: False, status: "replaces"}`.

  **Swapped-out versions.** For each `(old, new)` in `run.options.swaps` where `ev:{new}` is evidence, `ev:{old}` is not, and `old` is a known chunk: add a node `ev:{old}` with `status: "swapped_out"`, the step of `ev:{new}`, `agent: None`, `weight: 0`, `on_path: False`, `retired_on` and `days_out_of_date`. Add a `replaces` edge from `ev:{new}` to it. A run and its forks then draw the same node set, and the UI animates between them.
- **Claim nodes**, sorted by `(step, id)`:

  ```
  {id, type: kind, label: id.upper() for claims ("C3") or "Decision",
   text, value, column, step, agent, status, weight, on_path}
  ```

  The column is the last one for the decision, else `1 + agents.index(agent)`. Each attribution becomes an edge:

  ```
  {from: input, to: claim, type: "drove" | "context", share,
   on_path: drove and the claim and the input are both in path,
   status: "replaced" if drove and the source status is retired or replaced, else "current"}
  ```

- Returns `{columns, nodes, edges}`.

**`analyst_read(report)`** returns `{headline, text, sources}` (empty sources are dropped). Let `d` = decision value, `rp` = replay, `days` = days_out_of_date, and `bad` = the replaced claims.

- **Paused run.**
  - Headline: `f"Run paused at step {paused_at}. Nothing has been decided yet."`
  - Text: the message of the `breakpoint` event at `paused_at` (or `"A breakpoint rule fired."`), plus `f" Continuing with the current version leads to: {rp.decision_after}."` when the replay has a `decision_after`.
  - Sources: `[label of the first evidence item in bad[0].replaced_via, f"Breakpoint at step {n}"]`.
  - **Return here.** The stability suffix is not added.
- **Findings `confirmed_by_replay`, `outcome_unchanged`, `claim_used_replaced` and `decision_used_replaced`.**
  1. Build a chain with `_bad_chain`, starting at `"decision"` if the decision claim is `replaced`, otherwise at the lowest-step bad claim. From the current node, keep following `replaced_via[0]` and stop at the first evidence id.
  2. The hops are the friendly names `"the decision"` and `"claim 04"` (via `_name`), ending with the evidence label.
  3. `story = f"{hop0} rests on {hop1}" + "".join(f", which rests on {h}" for h in rest)`, with the first letter capitalised.
  4. Sources: `[label, f"Retrieval at step {src.step}", f"Replay {rp.run_id}"]`.

  | Finding | Headline | Text |
  |---|---|---|
  | `confirmed_by_replay` | `f"{'Approved' if d == 'approve' else 'Decided'} on a policy retired {days} days earlier."` | `f"{story}. That version stopped applying on {fmt_day(retired_on)}. Replaying with {current_label} changes the decision from {before} to {after}."` |
  | `outcome_unchanged` | `f"Used a policy retired {days} days earlier, but the outcome holds."` | `f"{story}. Replaying with {current_label} leaves the decision unchanged ({after}). The retrieval index should stop serving the retired version."` |
  | the other two | `f"A claim rests on a source retired {days} days earlier."` | `f"{story}. It is not on the path to the decision, but should be corrected."` |

- **Finding `retired_in_context`.** Headline `"A retired source was retrieved but did not drive any claim."`. Text `"No claim depends on it. The retrieval index still serves the retired version."`.
- **Finding `unsourced`.** Headline `"Evidence is current, but one claim has no source."`. Text: the capitalised names of the nosource claims, joined with `", "`, followed by `" came from the model's own knowledge. A reviewer should confirm it."`.
- **Finding `healthy`.** Headline `"Every claim is backed by current evidence."`. Text `"No replaced sources and no unsupported claims in this run."`.
- **Stability suffix** (every case except a paused run). If stability is not stable, append `f" The decision is unstable: {', '.join(f'{v} {k}' for k, v in counts.items())} out of {samples} samples."`.

### 7.10 `service.py`: `class Supersede`

**Constructor:** `__init__(store=None, *, llm=None, samples=10)`.
- `store` defaults to `SQLiteStore(env SUPERSEDE_DB or "supersede.db")`.
- `kb = kyc.knowledge()`.
- The model mode is `llm`, else env `SUPERSEDE_LLM`, else `"mock"`, lowercased. `"azure"` uses `AzureOpenAIClient()`; anything else uses `kyc.mock_llm()`. The mode is kept in `llm_mode`.
- It also sets `rules = default_rules()`, `runner = Runner(store, kb, llm, kyc.workflow(), rules)` and `analyzer = Analyzer(runner)`.
- **`_lock = threading.RLock()`.** The API serves requests on several threads. `report`, `start_run`, `resume`, `fork`, `set_rule` and `reset_demo` all run under this lock. Without it, two requests for a not-yet-analysed run could each create a replay fork. The lock is re-entrant because `fork` and `resume` call `report`. `report` takes the lock and calls `_report`, which holds the logic described below.

**Methods**

- **`seed_demo()`:** does nothing if any runs exist. Otherwise it starts each customer with `runner.start(subject=name, inputs=customer_inputs(c), run_time, options, run_id=c.run_id, created_at=c.created_at)`.
- **`reset_demo()`:** `store.clear()` followed by `seed_demo()`.
- **`start_run(*, customer_id=None, inputs=None, run_time="2026-10-15", options=None)`:**
  - With a customer id, it uses that customer's inputs, name and run_time. Without one, the subject is `inputs["name"]`.
  - It starts a run with `options or {"breakpoints": True}` and `run_id = new_id("KYC")`, then returns `report(id)`.
- **`report(run_id, *, refresh=False)`:**
  - Raises `KeyError` for an unknown run.
  - Uses the cached analysis unless `refresh` is set, the cached `version` is not `REPORT_VERSION`, or the cached `run.status` or `run.paused_at` differs from the live run. Otherwise it calls `analyzer.analyze(run_id, samples=self.samples)`.
  - It then copies the report and adds:
    - `run`: the live row;
    - `events`;
    - `feedback`;
    - `forks`: a `_brief` of each child;
    - `parent`: a `_brief` of the parent, or None;
    - `rules`: `[{**rule.describe(), "on": options.rules.get(key, default_on)}]`.
- **`_brief(run)`:** `{id, status, forked_at, fork_reason, swaps: options.swaps or {}, created_at}`.
- **`summary(run_id)`:** `{id, workflow, subject, status, run_time, created_at, paused_at, decision (value), finding, finding_label, counts, days_out_of_date, replay_decision (replay.decision_after), stability, forks (count)}`.
- **`list_runs(*, include_forks=False)`:** summaries of every run, top-level only unless `include_forks` is set, in store order.
- **`overview()`:**
  - `runs` is the top-level summaries.
  - **Exposure score**, used for ranking: 5 for `confirmed_by_replay`; 4 for a paused run; otherwise 3 for `decision_used_replaced`, 2 for `claim_used_replaced`, 1 for `outcome_unchanged`, and 0 for anything else.
  - `ranked` is the runs with an exposure score above 0, sorted by `(-score, created_at)`, first 5.
  - `replaced` has one entry for each `(old, new)` in `kb.replaced_by`, sorted by `on` descending:

    ```
    {old: old.label, new: new.label, on: new.effective_on, on_label: fmt_day(...), kind: old.kind,
     runs_using_old: [top-level run ids whose report evidence has chunk_id == old]}
    ```

  - It returns `{totals, ranked, replaced, llm: llm_mode}`, where `totals` is:

    | Key | Value |
    |---|---|
    | `runs` | number of top-level runs |
    | `paused` | runs with status `paused` |
    | `used_replaced` | runs with `counts.replaced > 0` |
    | `decision_affected` | runs whose finding is `confirmed_by_replay` or `decision_used_replaced` |
    | `unsourced_claims` | sum of `counts.nosource` |
    | `runs_with_unsourced` | runs with at least one nosource claim |

- **`state(run_id, step)`:** raises `KeyError(f"no checkpoint for step {step}")` if there is no checkpoint. Otherwise returns `{run_id, step, state: after, diff: state_diff(before or None, after), spans: [that step's spans]}`.
- **`resume(run_id, action, *, swaps=None, note="")`:** if the action is `edit` and no swaps were given, it uses `suggested_swaps` from the latest `breakpoint` event. It then calls `runner.resume` and returns `report(new_id, refresh=True)`.
- **`fork(run_id, *, from_step, swaps=None, guard=None, reason="manual fork")`:** options are `{"breakpoints": False}`, plus `"guard": guard` when guard is not None. It calls `runner.fork`, which may return an existing identical fork, and returns `report(new)`.
- **`set_rule(run_id, key, on)`:** sets `options.rules[key] = on`, updates the run and returns `report(run_id)`.
- **`add_feedback(run_id, verdict, note="", author="reviewer")`:** raises `ValueError("verdict must be correct, wrong or needs_review")` for any other verdict. Otherwise it stores `{id: new_id("fb"), run_id, verdict, note, author, at}` and returns `{run_id, feedback: [...]}`.

### 7.11 `__init__.py`

The package docstring lists the layers `store`, `knowledge`, `llm`, `tracing`, `runtime`, `rules`, `provenance` and `demo`, and states "Only the Python standard library is used here. FastAPI lives in `api/`." It also sets `__version__ = "0.1.0"`.

### 7.12 Module dependency order

`util` → `store` → `knowledge` → `llm` → `tracing` → `runtime` → `rules` (imports `Pause` from runtime) → `demo.kyc` → `provenance` → `service`.

### 7.13 Backend docs

- `backend/README.md` holds a short run book and the API table in section 8. Its run book should use `python -m uvicorn api.app:app --reload`.
- The root `README.md` holds run steps, the 3-minute demo script, a "How it works" table (one row per module) and Azure env-var setup.

### 7.14 `tests/test_engine.py` (22 tests, `unittest`)

The test module starts with:
- `V3, V4 = "edd-policy@v3#2.1", "edd-policy@v4#2.1"`;
- a helper `service()` that returns `Supersede(SQLiteStore(":memory:"), llm="mock")` after `seed_demo()`.

**`KnowledgeTests`** (setUp: `kb = kyc.knowledge()`)

- `test_versions`:
  - V3 is `current` on 2026-06-30 and `retired` on 2026-07-01;
  - `days_out_of_date(V3, "2026-10-15") == 106`;
  - `current_version(V3, "2026-10-15") == V4`, and `current_version(V3, "2026-03-01") == V3`.
- `test_plain_retrieval_prefers_retired_version`: searching the step-3 query with `top_k=2` over edd-policy and risk-guide puts V3 first, and V4 is absent.
- `test_guard_mode_swaps_retired_chunk`: `retrieve("enhanced due diligence escalation list", top_k=2, doc_ids=["edd-policy"], guard_day="2026-10-15")` gives V4 first, and `blocked == [{"from": V3, "to": V4}]`.

**`RunTests`**

- `test_historical_run_approves_on_retired_policy` (KYC-2041):
  - decision `approve`, finding `confirmed_by_replay`, days 106, first wrong step 3;
  - c3 and c4 are `replaced`, c5 is `nosource`, c1 is `current`;
  - `ev:V3` is in `decision_path`.
- `test_replay_flips_decision`:
  - the replay goes approve → escalate, `decision_changed`, and the changed claims are exactly `{c3, c4, decision}`;
  - the child report has `forked_at == 3`, and every step row before 3 is `cached`.
- `test_outcome_unchanged_when_policy_change_is_irrelevant`: KYC-2040's finding is `outcome_unchanged`.
- `test_stability`: KYC-2041 counts are `{"approve": 6, "escalate": 4}` and not stable. The replay run's counts are `{"escalate": 10}`.
- `test_attribution_finds_the_driving_chunk`: for c3, `ev:V3` drove it and `ev:risk-guide@v2#1` did not.
- `test_redundant_causes_share_credit`: in the replay run's decision, both c3 and c4 drove it, and `ev:edd-policy@v4#2.1` is in `decision_path`.
- `test_graph_shape`:
  - the node `ev:V4` exists;
  - a `replaces` edge exists;
  - the columns start with `Evidence` and end with `Outcome`.
- `test_replay_graph_keeps_swapped_out_version`: in the KYC-2041 replay's graph, `ev:V3` has status `swapped_out`, `ev:V4` has `swapped_in` true, and the node ids are the same as the parent's graph.

**`BreakpointTests`**

- `test_pauses_when_retired_policy_enters`: KYC-2036 is `(paused, 3, stale_evidence)` and has no checkpoint 4.
- `test_edit_forks_with_current_version_then_pauses_before_decision`:
  1. `resume("KYC-2036", "edit")` returns a child with parent KYC-2036, `paused` with `ungrounded_before_action`, and the parent becomes `forked`.
  2. Approving the child completes it with `escalate`.
- `test_approve_and_reject`:
  1. Approving KYC-2036 pauses it again with `ungrounded_before_action`.
  2. Rejecting it then gives `rejected`, and checkpoint 6 does not exist.
- `test_state_drawer`: `state("KYC-2041", 3)` has `ev:V3` in the added evidence, claims added `== ["c3"]`, and a `retrieval` span.
- `test_tool_loop_rule`:
  - Setup: a 2-step workflow whose first step calls `ctx.tool("lookup", lambda q: {"q": q}, label="Lookup", q="same")` three times, run with `[ToolLoopRule()]`.
  - The run pauses with `tool_loop`.
- `test_budget_rule`: the KYC workflow with `[BudgetRule()]` and options `{"rules": {"budget": True}, "model_call_limit": 2}` pauses with `budget`.
- `test_guard_mode_run`: `fork("KYC-2041", from_step=3, guard=True, reason="guard test")` decides `escalate`, and its events include `blocked`.

**`ServiceTests`**

- `test_overview`:
  - 5 runs, 1 paused;
  - `ranked[0].id == "KYC-2041"`;
  - `replaced[0].new == "EDD Policy v4 §2.1"`.
- `test_feedback`: verdict `wrong` is saved, and verdict `"maybe"` raises `ValueError`.
- `test_concurrent_reports_make_one_replay`: 4 threads call `report("KYC-2041")` at once on a fresh service, and KYC-2041 ends with exactly 1 child.
- `test_identical_fork_is_reused`: forking KYC-2041 from step 3 with `{V3: V4}` twice returns the replay run both times. A fork from step 4 is a new run, which leaves 2 children.

Run with `python -m unittest discover -s tests -v` from `backend/`.

---

## 8. HTTP API

Both servers create one `svc = Supersede()` at import time, call `svc.seed_demo()`, and serve these routes:

| Method | Path | Body / query | Calls |
|---|---|---|---|
| GET | `/api/health` | | `{"ok": true, "llm": svc.llm_mode}` |
| GET | `/api/overview` | | `svc.overview()` |
| GET | `/api/runs` | `?include_forks=true` | `svc.list_runs(include_forks=…)` |
| POST | `/api/runs` | `{customer_id?, inputs?, run_time="2026-10-15", options?}`; 400 `"give customer_id or inputs"` if both are missing | `svc.start_run(...)` |
| GET | `/api/runs/{id}` | `?refresh=true` | `svc.report(id, refresh=…)` |
| GET | `/api/runs/{id}/steps/{n}/state` | | `svc.state(id, n)` |
| POST | `/api/runs/{id}/resume` | `{action: approve\|edit\|reject, swaps?, note=""}` | `svc.resume(...)` |
| POST | `/api/runs/{id}/fork` | `{from_step >= 1, swaps?, guard?, reason="manual fork"}` | `svc.fork(...)` |
| POST | `/api/runs/{id}/rules` | `{key, on}` | `svc.set_rule(...)` |
| POST | `/api/runs/{id}/feedback` | `{verdict: correct\|wrong\|needs_review, note="", author="reviewer"}` | `svc.add_feedback(...)` |
| POST | `/api/demo/reset` | | `svc.reset_demo()`, then returns `{"ok": true, "runs": count}` |

**`api/app.py` (FastAPI)**

- `FastAPI(title="Supersede", version="0.1.0", description="Decision provenance for AI agents")`.
- `CORSMiddleware` allows the origins `http://localhost:5173` and `http://127.0.0.1:5173`, with all methods and headers.
- Request bodies are pydantic models:
  - `StartRun`;
  - `Resume`: `action` uses `Field(..., pattern="^(approve|edit|reject)$")`;
  - `Fork`: `from_step` uses `Field(..., ge=1)`;
  - `RuleToggle`;
  - `Feedback`: `verdict` uses a pattern.
- `_call(fn, ...)` maps `KeyError` to 404 `"not found: {exc}"` and `ValueError` to 400 with the message.
- At the end of the file: if `Path(__file__).resolve().parents[2] / "frontend" / "dist"` exists, it does `app.mount("/", StaticFiles(directory=dist, html=True), name="ui")`.

**`api/stdlib_server.py`**

- **Routing:** a `ROUTES` list of `(method, compiled regex with named groups id/step, handler name)`. A `handle(name, path_params, query (parse_qs), body)` function mirrors the routes above.
  - It raises `ValueError("action must be approve, edit or reject")` for a bad resume action.
  - Booleans in query strings are true only when the value is `"true"`.
- **`Handler(BaseHTTPRequestHandler)`:**
  - JSON responses use `ensure_ascii=False, default=str` and carry `Access-Control-Allow-Origin: *`.
  - Errors: `KeyError` gives 404 `{"detail": "not found: …"}`; `ValueError` or `TypeError` gives 400; any other exception gives 500 and prints a traceback. Unknown `/api` paths give 404 `"no such route"`.
  - Non-`/api` paths serve static files from `DIST`, which is env `SUPERSEDE_DIST` or `<repo>/frontend/dist`. A path outside `DIST`, or a missing file, falls back to `index.html`. If there is no dist folder, it returns 404 `"frontend not built; run npm run build in frontend/"`.
  - `do_OPTIONS` returns 204 with Allow-Origin `*`, Methods `GET, POST, OPTIONS` and Headers `Content-Type`.
  - `log_message` writes `"{METHOD} {path}"` to stderr.
- **Startup:** `main(port=8000)` runs `ThreadingHTTPServer(("127.0.0.1", port))` and prints `Supersede API on http://127.0.0.1:{port}  (model: {mode})`. The port can be passed as `argv[1]`. Run it with `python -m api.stdlib_server`.

---

## 9. Frontend

### 9.1 Config

- **`package.json`:** name `supersede-ui`, private, version `0.1.0`, `"type": "module"`.
  - Scripts: `dev: vite`, `build: tsc --noEmit && vite build`, `typecheck: tsc --noEmit`, `preview: vite preview`.
  - Dependencies: `react ^18.3.1`, `react-dom ^18.3.1`.
  - Dev dependencies: `@types/react ^18.3.3`, `@types/react-dom ^18.3.0`, `@vitejs/plugin-react ^4.3.1`, `typescript ^5.5.4`, `vite ^8.3.5`.
- **`tsconfig.json`:** target ES2020, lib `[ES2020, DOM, DOM.Iterable]`, module ESNext, moduleResolution `bundler`, jsx `react-jsx`, strict, noUnusedLocals, noUnusedParameters, noFallthroughCasesInSwitch, skipLibCheck, isolatedModules, noEmit, resolveJsonModule. Include `["src", "vite.config.ts"]`.
- **`vite.config.ts`:** `react()` plugin, `server.port 5173`, `proxy: { "/api": "http://127.0.0.1:8000" }`.
- **`index.html`:** title `Supersede`, a viewport meta, and Google Fonts preconnect plus the stylesheet `family=Public+Sans:wght@400;500;600;700&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,500;1,8..60,400&display=swap`. The body has `<div id="root">` and `<script type="module" src="/src/main.tsx">`.
- **`frontend/README.md`:** the commands, plus a one-line description of each main file.

### 9.2 Core modules

- **`main.tsx`:** `createRoot(#root).render(<StrictMode><App/></StrictMode>)` and imports `./styles.css`.
- **`App.tsx`:**
  - A hash router hook, `useRoute()`, returns `location.hash` minus the `#`, defaulting to `/`, and updates on `hashchange`.
  - The route `/runs/<id>` renders `<Decision runId={decodeURIComponent(id)}/>`. Anything else renders `<Overview/>`.
  - `Decision` is **not** keyed by run id. Moving between a run and its forks keeps the page mounted, so the graph animates instead of reloading.
  - The layout is `<div className="app"><Header active="runs"|"decision"/>…</div>`.
- **`router.ts`:** `go(path)` sets `location.hash`. `runPath(id)` returns `/runs/${encodeURIComponent(id)}`.
- **`api.ts`:**
  - `request<T>(path, init)` fetches `/api${path}` with a JSON content type.
  - On a non-OK response it throws `Error(detail)`, using the JSON `detail` if it can be read, else `statusText`, and stringifies a non-string detail.
  - `post(path, body)` is a JSON POST.
  - The `api` object has: `overview()`, `runs()`, `report(id)`, `state(id, step)`, `resume(id, action, swaps?)`, `fork(id, fromStep, swaps, reason)` (sends `{from_step, swaps, reason}`), `setRule(id, key, on)`, `feedback(id, verdict, note="")`, `startRun(customerId)` (sends `{customer_id, options: {breakpoints: true}}`) and `resetDemo()`. Ids are URI-encoded.
- **`types.ts`:** mirrors the backend shapes. The full list:

```ts
type Status = "current"|"replaced"|"nosource"|"retired"|"not_retrieved"|"not_yet_effective";
type RunStatus = "running"|"paused"|"completed"|"rejected"|"forked";
type Finding = "healthy"|"unsourced"|"retired_in_context"|"claim_used_replaced"|"decision_used_replaced"|"outcome_unchanged"|"confirmed_by_replay";
interface Run { id; workflow; subject; status: RunStatus; run_time; parent_run_id: string|null; forked_at: number|null; fork_reason: string|null;
  paused_at: number|null; pause_reason: string|null; options: { breakpoints?; guard?; swaps?: Record<string,string>; rules?: Record<string,boolean> }; created_at }
interface Counts { claims; current; replaced; nosource; evidence; unused_evidence }            // numbers
interface Stability { samples: number; counts: Record<string,number>; stable: boolean; agreement: number }
interface RunSummary { id; workflow; subject; status; run_time; created_at; paused_at; decision: string|null; finding; finding_label;
  counts: Counts; days_out_of_date: number; replay_decision: string|null; stability: Stability|null; forks: number }
interface Overview { totals: { runs; paused; used_replaced; decision_affected; unsourced_claims; runs_with_unsourced };
  ranked: RunSummary[]; replaced: { old; new; on; on_label; kind; runs_using_old: string[] }[]; llm: string }
interface Evidence { id; kind: "chunk"|"tool"; label; text; step; agent; chunk_id?; version_status?: Status; days_out_of_date?; current_label?; retired_on?: string|null }
interface Attribution { input; share; change; drove: boolean; supports: boolean|null }
interface Claim { id; text; agent; step; inputs: string[]; value: string|number|null; kind: "claim"|"decision"; status: Status;
  replaced_via: string[]; attribution: Attribution[]; main_source: string|null }
interface GraphNode { id; type: "evidence"|"claim"|"decision"; kind?; label; text; value?; column; step; agent: string|null; status: Status;
  weight; on_path: boolean; retired_on?; days_out_of_date? }
interface GraphEdge { from; to; type: "drove"|"context"|"replaces"; share: number|null; on_path: boolean; status: "replaced"|"current"|"replaces" }
interface StepRow { step; name; label; agent; irreversible; ran; cached; seconds; tokens; model_calls; tool_calls; retrievals }
interface Replay { run_id; status; from_step; swaps; decision_before; decision_after; decision_changed; claims: {id; before; after: string|null; changed}[] }
interface RunEvent { id; run_id; step: number|null; kind: "breakpoint"|"resumed"|"forked"|"blocked"|"rejected";
  detail: Record<string,unknown> & { message?; rule?; suggested_swaps?: Record<string,string> }; at }
interface Brief { id; status; forked_at; fork_reason; swaps; created_at }
interface Rule { key; label; when: "before"|"after"; default_on; on }
interface Report { run; last_step; decision: {value; text}|null; finding; finding_label; first_wrong_step: {step; agent; label}|null;
  days_out_of_date; evidence: Record<string,Evidence>; claims: Record<string,Claim>; decision_path: string[]; replay: Replay|null;
  stability: Stability|null; steps: StepRow[]; counts; graph: {columns: string[]; nodes: GraphNode[]; edges: GraphEdge[]};
  read: {headline; text; sources: string[]}; events: RunEvent[]; feedback: {id; verdict; note; author; at}[]; forks: Brief[]; parent: Brief|null; rules: Rule[] }
interface Span { id; step; agent; kind; name; input: unknown; output: unknown; chunk_ids: string[]; tokens_in; tokens_out; started; ended; error: string|null; cached: number }
interface StepState { run_id; step; state: { evidence; claims; messages: {from; to; step; claim_ids}[]; scratch: Record<string,Record<string,unknown>>; decision };
  diff: { evidence: {added; changed; removed}; claims: {added; changed; removed}; messages: {added: {from; to; claim_ids}[]};
          scratch: Record<string,Record<string,unknown>>; decision: {value; text}|null }; spans: Span[] }
```

(Write out the full field types in the real file. Ids, labels and text are `string`; counts, steps, seconds and weights are `number`.)

- **`format.ts`**:
  - `day(value)` cuts the string instead of parsing it, so there are no timezone shifts: `"2026-07-01"` becomes `1 Jul 2026`, and empty input gives `""`.
  - `when(iso)` returns `"{day}, HH:MM"`.
  - `pct(share)` returns `"—"` for null, else the rounded percentage, for example `"57%"`.
  - `claimName(id)` returns `"Decision"`, or `Claim 03` for `c3`, or the raw id.
  - `decisionWord(v)` maps approve to `Approve account`, escalate to `Escalate to EDD` and refer to `Refer to an analyst`. Anything else returns the value itself, or `Not decided` if it is null.
  - `statusWord` maps the statuses to Current, Replaced, Retired, No source, Not retrieved and `Not yet in force`. `runStatusWord` maps the run statuses to Running, Paused, Completed, Rejected and Forked.
  - `findingTone(f, status?)` returns `"bad"`, `"warn"` or `"ok"`:
    - `bad` if the run is paused, or the finding is confirmed_by_replay, decision_used_replaced or claim_used_replaced;
    - `warn` if the finding is unsourced, outcome_unchanged or retired_in_context;
    - `ok` otherwise.

### 9.3 `layout.ts`: hand-rolled graph layout

This follows design v2. Evidence is on the left, there is one column per agent, and the outcome is on the right. Claims step down in run order, each piece of evidence sits level with the claim it feeds, and the decision sits in the vertical middle. **Positions depend only on the graph's structure, never on statuses**, so a run, its replay and its forks share one layout and animate between each other.

The layout and router must stay readable for any number of agents, steps, claims per step and inputs, including agents that work again later in the run. The key property is that **every claim has a row of its own**, so a horizontal line along a claim's row can never hit another box. Edges run along rows and turn only in the empty lanes between columns.

**Constants:**

| Name | Value | Meaning |
|---|---|---|
| `TOP` | 56 | below the column heads |
| `FIRST_ROW` | 44 | centre of the first claim, below `TOP` |
| `CLAIM_ROW` | 86 | row pitch |
| `EVIDENCE_X` | 60 | evidence dot centre |
| `EV_LABEL_W` | 196 | `.dot-label` width |
| `EV_MAX_R` | 22 | largest evidence dot radius |
| `FIRST_AGENT_X` | 350 | left edge of the first agent column |
| `AGENT_W` | 210 | column pitch: a pill plus a 50 px lane |
| `PILL_W`, `PILL_H` | 160, 66 | claim box |
| `DECISION_R` | 32 | smallest outcome radius |
| `MAX_DECISION_R` | 64 | largest outcome radius |
| `DECISION_LABEL_W` | 140 | `.decision-label` width; lanes stop before it |
| `EV_GAP` | 60 | least distance between evidence dots |
| `FAMILY_GAP` | 72 | between versions of one source |
| `LABEL_ROOM` | 48 | under the lowest node |
| `PORT_GAP` | 12 | between edges on one side of a box |
| `LANE_PAD` | 8 | turns keep this far from boxes |
| `MIN_SLOT` | 8 | least spacing of turns in one lane; lanes widen to fit |
| `STRAIGHT_DY` | 20 | ends closer than this are joined straight |
| `MAX_CORNER` | 28 | corner radius cap |

**`radius(n)`:** 32 for the decision node, otherwise `round(8 + min(1, weight) * 14)`. In the layout the outcome uses `decisionR` instead (below).

**`laneOf(a, b, last)`** gives the lane an edge turns in. Lane *j* is the gap on the left of column *j*.
- Forward from evidence: lane 1, so the edge turns right after the evidence column and then runs along the target's row.
- Forward from a claim: lane `b.column`, so it runs along the source's row and turns just before the target.
- Backward (`a.column > b.column`): lane `b.column + 1`, the gap on the right of the target column.
- Same column: lane `a.column + 1`, capped at `last`.

**`layoutGraph(columns, nodes, edges, extra = 0)`** returns `{width, height, columns: [{name, x}], nodes: Placed[], byId, lanes: [{from, to}]}`. Call it with `extra = 0` to get the natural width.

1. **Outcome size.** `inputs` is the largest number of non-`replaces` edges into one decision node. `decisionR = min(MAX_DECISION_R, max(DECISION_R, (inputs - 1) * PORT_GAP / 2 + 10))`, so every input gets its own port. `reach = max(decisionR, DECISION_LABEL_W / 2)`: the outcome column reaches this far left.
2. **Column x.**
   - Base positions: column 0 at `EVIDENCE_X`; agent column *i* at `FIRST_AGENT_X + PILL_W/2 + (i-1) * AGENT_W`; the outcome at `FIRST_AGENT_X + agents * AGENT_W + reach`.
   - Lane widening: `demand[j]` counts the edges whose `laneOf` is *j*. Walking the columns left to right, column *i* shifts right by the running total of `max(0, demand[i] * MIN_SLOT + 2 * LANE_PAD - baseLaneWidth[i]) + gap`, where `gap = extra / (cols - 1)` is the big-screen spread.
   - Lane *j* is the range `[rightEdge(j-1) + LANE_PAD, leftEdge(j) - LANE_PAD]`. For column 0 the right edge is `EVIDENCE_X + EV_MAX_R + 8 + EV_LABEL_W`; for agents it is `x + PILL_W/2`. The left edge is `x - PILL_W/2` for agents and `x - reach` for the outcome.
3. **Claims.** Sort the claims by `(step, id)`. Claim *i* gets `y = TOP + FIRST_ROW + i * CLAIM_ROW`.
4. **Outcomes.** Sorted by `(step, id)`. Outcome *k* of *n* gets `y = middle + (k - (n-1)/2) * CLAIM_ROW`, where `middle` is the midpoint of the highest and lowest claim y.
4. **Evidence.**
   - **Target.** An evidence node's target is the y of the claim it feeds. Among its non-`replaces` edges, pick drove before context, then the highest share, then the highest target.
   - **Families.** Nodes joined by `replaces` edges form a family. A family is placed as one block: members sorted by version (`@v(\d+)#` in the id), and its target is the lowest target among its members.
   - **Placement.** Sort the units by `(target, step, id)`, with units that have no target last. Place them top-down with a cursor that starts at `TOP + FIRST_ROW`:
     - the first member goes at `max(target, cursor)`;
     - each further member goes `FAMILY_GAP` lower;
     - then `cursor = last y + EV_GAP`.
6. **Shapes.** Claims are `pill`s (`PILL_W × PILL_H`). The outcome is a circle of radius `decisionR`. Evidence nodes are circles of radius `radius(n)`. `x` is the column x, which is the node's centre.
7. **Size.** `width = outcomeX + reach + 24` and `height = lowest node bottom + LABEL_ROOM`.

**`routeEdges(layout, edges)`** returns `{"{from}-{to}": {d, pts}}`: an SVG path and the polyline it was built from. Pass only the edges on screen, so hidden ones don't take up ports or lane slots.

1. **`replaces` edges:** a straight line from the bottom of the upper dot to the top of the lower dot.
2. **Plan each other edge.**
   - **Forward:** leaves from the right side of a claim, or from the right edge of an evidence dot with no port. It enters the target's left side.
   - **Backward:** leaves the source's left side and enters the target's right side.
   - **Same column:** if no other node in that column lies between the two, it is a straight vertical line from the bottom of the upper node to the top of the lower one ("straight-down"). Otherwise it goes "around": out of the right side of `a`, through the lane on the right of the column, and into the right side of `b`.
3. **Ports.** For each side of each node, sort its edges by the y of their other end (then x) and spread them `sp = min(PORT_GAP, (h - 2 * inset) / (n - 1))` apart around the centre. The inset is 12 for pills and 8 for circles. On a circle the port x lies on the circle at that height.
4. **Lane slots.** An edge turns only if its ends differ by `STRAIGHT_DY` or more ("around" edges always turn). Each turning edge gets its own x in its lane: the lane's width is split evenly between them.
   - Ordering keeps turns nested instead of crossing: for claim → later column, slots are ordered by `|dy|` ascending, so the longest drop turns nearest the target; for evidence, backward and around edges, by `-|dy|`.
5. **Points.** A straight edge is `[[sx, sy], [tx, ty]]`. A turning edge is `[[sx, sy], [x, sy], [x, ty], [tx, ty]]`. The path rounds each corner with radius `min(MAX_CORNER, half of each adjacent segment)`, so short drops become a smooth S.

### 9.4 `components/Header.tsx`

- `<header className="topbar">` contains the brand link `#/`.
- The brand has a 26×26 inline SVG and the word `Supersede`. The SVG is a rounded rect `#0E1D21`, a coral dot at (8, 17) r 2.5 `#FF6A55`, a teal dot at (18, 9) `#43C6AC`, and a line `M10 15.5L16 10.5` in stroke `#E6EEEC` width 1.6.
- `nav.topnav` (aria-label "Main") has two links, `Runs` (`#/`) and `Decision graph` (`#/runs/KYC-2041`). The active one gets `aria-current="page"`.
- On the right: `<span className="topbar-note">Harborline Bank, synthetic data</span>`.

### 9.5 `components/EvidenceGraph.tsx`

Props: `{report, tone: "run"|"now", visibleStep, selected, onSelect, filters: GraphFilters, children?}`. `GraphFilters` is exported as `{documents, tools, context}`.

- **Node filtering.** Non-evidence nodes always show. Tool evidence shows if `filters.tools` is on; other evidence shows if `filters.documents` is on.
- **Fit to width.** Constants: `WRAP_PADDING = 24`, `MAX_SPREAD = 1.35`, `MAX_SCALE = 1.35`. A `ResizeObserver` on the wrapper stores `avail = clientWidth - WRAP_PADDING`. The natural width depends on the graph, because lanes widen and the outcome grows, so `base = layoutGraph(columns, shownNodes, edges, 0)` and `natural = base.width`:
  - **Narrow** (`avail <= natural`): `scale = max(0.7, avail / natural)` and `extra = 0`. Below 0.7 the wrapper scrolls.
  - **Wide**: first spread the columns, with `spread = min(avail, natural * MAX_SPREAD)` and `extra = spread - natural`. Then scale up with `scale = min(MAX_SCALE, avail / spread)`.
  - Before the first measurement (`avail` is 0), `scale = 1`.
  - The layout is `extra > 0 ? layoutGraph(columns, shownNodes, edges, extra) : base`.
  - `shownEdges` is the edges whose ends are both laid out, minus context edges when `filters.context` is off. Then `routes = routeEdges(layout, shownEdges)`.
  - The DOM is `div.graph-wrap > div.graph-sizer(width × scale, height × scale) > div.graph-stage(width, height, transform: scale())`.
- **Visibility.** `visible(id)` means the node's step is no higher than `visibleStep` (unknown ids count as step 99).
- **Path colour.** `healthy = tone === "now" || counts.replaced === 0`. `flowTone(status)` is `bad` for replaced, `good` when healthy, else `neutral`.
- **Column headers.** `div.col-head`, centred on the column x. The half-width is `x` for column 0 and 80 for the others. There are no step row rules.
- **Edges.** One `svg.edges` holds every edge in `shownEdges` as `<g key="{from}-{to}" className={visible ? "" : "is-hidden"}>`, drawn with `routes[key].d`.
  - The path class is:
    - `edge edge-replaces` for `replaces` edges. These also get an SVG `<text class="edge-label" text-anchor="end">replaces</text>`, 10 px left of the line at its midpoint;
    - `edge edge-nosource` for `context` edges whose source has status `nosource` (amber dashed);
    - `edge edge-context` for other `context` edges;
    - `edge edge-path {tone}` for `on_path` edges;
    - `edge edge-bad` for replaced-status edges;
    - `edge edge-drove` otherwise.
  - Stroke width is `1.25 + share * 2.25` for drove edges, else 1.25.
  - On-path edges get a second overlay path, `edge-flow {tone}`, which animates dashes.
- **Claim pills.** `<button class="node pill n-{status} [is-selected] [is-hidden]">`, positioned absolutely by the box.
  - Inside: `span.pill-top` holds the claim name and, if the status is not current, `span.pill-status` with the status word. `span.pill-text` holds the text.
  - `aria-label`: `"{Claim 03}, {Status}: {text}"`. `aria-pressed` is set when selected.
- **Circles (evidence and decision).** `div.node-wrap` contains `button.node.dot[.decision].n-{status}` (w × h), plus a label.
  - Decision: `div.dot-label.decision-label` sits below the node (`top: h + 8`, `left: w/2 - 70`) and shows `decisionWord(value)`.
  - Evidence: `div.dot-label` sits to the right of the dot, under the edge that leaves it (`left: w + 8`, `top: h/2 + 3`). It holds `span.dot-title` (the label) plus at most one note:
    - retired: `dot-note bad` `"retired, {days} days old"`;
    - not retrieved: `dot-note good` `"in force, replaces v{version - 1}; not retrieved"` (the version is parsed from ` v(\d+) ` in the label);
    - swapped out: `dot-note` `"swapped out in this run"`;
    - swapped in: `dot-note good` `"swapped in for v{version - 1}"`;
    - tool: `dot-note` `"tool result"`.
- `children` render inside the stage.

### 9.6 `components/Panels.tsx`

`chipTone` maps statuses to tones: current→ok, replaced→bad, retired→bad, nosource→warn, not_retrieved→quiet, not_yet_effective→quiet, swapped_out→quiet. In `NodeDetail`, a swapped-out node gets the kicker "Document, swapped out" and the note "This run was forked with the current version in its place, so the agents never saw this one."

**`AnalystRead({report})`**

- `section.card.pad` (aria-label "Analyst read").
- The tone is `bad` if `counts.replaced > 0` or the run is paused, else `warn` if nosource > 0, else `ok`.
- The header row shows `span.dot-mark.tone-bg-{tone}` and "Analyst read".
- Then `p.serif.read` with `read.text`, and a row of `span.source-chip`, one per source.

**`NodeDetail({report, id})`**

- With no id: "Select a node in the graph to see what drove it."
- Otherwise:
  - **Kicker:** for a claim, "Outcome" (decision) or "Claim by the {agent}"; for evidence, "Tool result" or "Document"; else "Document, not retrieved".
  - **Title** (`h3.h3`): the claim name or the node label. A `status-chip tone-{chipTone}` shows the status word.
  - `blockquote.quote.tone-border-{tone}` holds the text.
  - **Retired evidence:** `p.small.tone-bad` "Replaced on {day} by {current_label}. It was {n} days out of date on the run date."
  - **Not retrieved:** "This is the version in force on the run date. The agent never saw it."
  - **"What drove it (leave-one-out)":** a `ul.bars` of attributions sorted by share, descending. Each row shows the label (evidence label or claim name) and `pct(share)`, or "did not drive it". Below it is `div.bar > span` with width = share if drove, else 0. The fill class is `fill-bad` if the input is a replaced claim or retired evidence, `fill-ok` if it drove, and nothing otherwise.
  - **A claim with no attributions:** `p.small.tone-warn` "Nothing in the agent's context explains this claim. It most likely came from the model's own knowledge."
  - **"Drove: Claim 04 (43%), …"**: the claims this node drove.
  - `div.facts` shows Step and Agent.

**`StabilityCard`**

- Hidden when there is no stability data.
- Heading "How stable is the decision?" with "{n} samples" beside it.
- `div.stack-bar` (role img) has one segment per outcome, sorted by count descending. `approve` uses `fill-ink`; other outcomes use `fill-ok`. Below it is a row of "**6** approve".
- Note: "All {n} re-samples of the decision step agree." when stable, else "Re-sampling the decision step gave different answers. An unstable decision is a risk signal on its own."

**`FeedbackCard`**

- Heading "Mark this decision".
- Three `button.chip` buttons, Correct, Wrong and Needs review, with `on` and `aria-pressed` on the saved one. The initial value is the last feedback verdict.
- A `label.field` holds the note input ("Note for the audit trail (optional)", placeholder "Why?").
- Clicking a chip posts the feedback, sets the saved verdict and clears the note. Afterwards it shows `Saved as “Wrong”.` (with curly quotes).

### 9.7 `components/StateDrawer.tsx`

Props: `{runId, step, label, onClose}`.

- It fetches `api.state` on mount and on change, and closes on Escape.
- **Container:** `div.drawer-backdrop`, which closes on click, wraps `aside.drawer` (`role="dialog"`, `aria-modal`, aria-label `"State after step N"`; clicks inside it don't propagate).
- **Header:** "State after step N", `h2.h3` with the label, and `button.btn.btn-quiet` "Close" (autoFocus).
- **Loading and errors:** "Loading…" while fetching; errors render as `p.error`.
- **Sections:**
  1. **"Added to the context"**: added evidence, each as `span.diff-add "+"` with the label (strong) and `clamp-2` text. Shows "No new evidence." when empty.
  2. **"Claims made"**: added claims with name and text. Shows "No new claims." when empty.
  3. **"Handed over"**: shown only if messages were added. Each line is `→ "{from} to {to}: Claim 01, Claim 02"`.
  4. **"Working memory"**: shown only if the scratch diff is non-empty, as a `pre.code` with the JSON.
  5. **"Calls in this step"**: a `table.table.compact` of the non-`invoke_agent` spans. Columns:
     - Kind: the kind with `_` replaced by a space;
     - Name: plus " (reused)" if cached;
     - Time: `"{(ended - started).toFixed(2)} s"`;
     - Tokens: in + out, or "—".

### 9.8 `pages/Overview.tsx`

- **State:** `data`, `runs`, `filter` (`all|bad|warn|ok`), `busy` and `error`.
- **Loading:** `load()` fetches `overview` and `runs` in parallel.
  - Before data arrives: "Loading runs…".
  - If loading fails with no data: `p.error[role=alert]` "Could not reach the API: {msg}. Start the backend on port 8000."
- **Attention band:** `section.attention` (dark).
  - Headline (`h1.serif`): `"{n} decision rests on a retired policy."` or `"{n} decisions rest on a retired policy."`. When n is 0: `"No decision rests on a retired policy."`.
  - Paragraph: "{used_replaced} of {runs} runs read a replaced source. Replay with the current version shows which of them would have decided differently. Standard tracing marked every one of these runs as successful."
  - Buttons:
    - `a.btn.btn-light` "Open the worst case", linking to `ranked[0]`;
    - `button.btn.btn-ghost-dark` "Run KYC-2041 again with breakpoints on", which calls `api.startRun("KYC-2041")` and then navigates to the new run.
  - `ol.ranked` (aria "Ranked by exposure"). Each item shows:
    - its index;
    - a link `"{id}, {subject}"`;
    - a sub line: `"Paused at step N, waiting for a reviewer"` if paused, else `"{decisionWord} as run; replay with current versions: {decisionWord(replay_decision)}"`;
    - `span.ranked-tag.bad|warn` with "Decision on hold" if paused, else the finding label. The tag is `bad` for confirmed_by_replay or paused runs, otherwise `warn`.
- **Tiles** (`section.tiles`, four `Tile`s):

  | Label | Value | Note | Tone |
  |---|---|---|---|
  | Runs traced | runs | "KYC onboarding" | |
  | Paused by a breakpoint | paused | "waiting for a reviewer" | |
  | Read a replaced source | used_replaced | "decision changed on replay: {decision_affected}" | bad |
  | Claims without a source | unsourced_claims | "in {n} runs" | warn |

- **`div.split`** holds two cards.
  - **All runs.** `section.card.grow` with a card head "All runs" and filter chips "All N", "Needs action N", "Check N" and "Healthy N". The filter uses `findingTone`. The table columns are Run, Subject, Decision, Claims, Finding and When:
    - Run: the id as a link, with the status word below it.
    - Decision: "Paused at step N" or the decision word.
    - Claims: a `HealthBar`.
    - Finding: `strong tone-{tone}`, showing "Waiting at a breakpoint" if paused, else the finding label.
    - When: `when(created_at)`.
  - **Recently replaced.** `aside.card.side` with the note "Sources that changed, and the runs still reading the old version." It has an `ol.timeline`. Each item shows:
    - `"{on_label}, {kind}"`;
    - strong `"{new} replaced {old with everything before ' v' stripped}"`, which shows as `v3 §2.1`;
    - `tone-bad` `"{n} runs still read the old version"`, or `tone-ok` "No runs affected".

    Below the list: `button.btn.btn-quiet` "Reset demo data", then "Model: offline mock (scripted)" (or the mode name).
- **`HealthBar`:** a 120 px `div.health` (role img) with `h-ok`, `h-bad` and `h-warn` segments in proportion to claims. The caption reads "{c} current, {r} replaced, {n} without a source".

### 9.9 `pages/Decision.tsx` (main screen)

**State**

| Variable | Initial value |
|---|---|
| `report` | |
| `replay` | the replay run's report |
| `mode` | `run` (the other value is `now`) |
| `view` | `graph` (the other value is `table`) |
| `visibleStep` | 99 |
| `playing` | |
| `simPause` | |
| `bpPassed` | |
| `selected` | |
| `drawerStep` | |
| `filters` | all on |
| `busy` | |
| `error` | |
| `timer` | interval ref |

The constant `PLAY_MS = 900`.

The page stays mounted when `runId` changes (see `App.tsx`). It never shows "Loading…" again after the first report, so the graph's nodes, which are keyed by id, animate from the old run to the new one.

**`show(rep, playFrom?)`** (a `useCallback`)

1. Stop play. Set the report, set `mode = "run"`, and clear `simPause`, `bpPassed` and `error`.
2. Keep `selected` if that id exists in the new report. Otherwise select the first retired evidence item, else `"decision"`, else null.
3. If `playFrom` is given, call `startPlay(rep.last_step, playFrom, null, true)`. Otherwise set `visibleStep = last_step`.
4. If the report has a replay, fetch the replay run's report.

**Loading effect** (on `runId`): if `preloaded.current === runId`, clear it and do nothing, because the report is already shown. Otherwise fetch the report and call `show`, ignoring the result if the effect was cleaned up. The timer is stopped on unmount. `shown` is the replay report when `mode === "now"` and a replay exists, else the main report.

**Derived values**

- `staleRuleOn`: the `stale_evidence` rule is on.
- `simStep`: the step where a simulated breakpoint would fire. It is `first_wrong_step.step` when the mode is `run`, the run is `completed`, `first_wrong_step` exists and `staleRuleOn` is true; otherwise null.
- `realPause`: the mode is `run` and the run is `paused`.
- `pauseEvent`: the latest `breakpoint` event.

**`startPlay(max, from, sim, passedAlready)`**

1. Set `visibleStep = from`. If `from >= max`, stop here.
2. Otherwise, every `PLAY_MS`, step forward by one.
3. On reaching `sim` while not yet passed: mark it passed, set `bpPassed` and `simPause`, and stop.
4. Stop at `max`.

**`play()`**

1. If playing, stop and return.
2. Clear `simPause`. Let `max = shown.last_step` and `restart = visibleStep >= max`.
3. Call `startPlay(max, restart ? 0 : visibleStep, simStep, restart ? false : bpPassed)`.

**`act(fn, then)`** wraps a call with the busy flag and error handling.

**`openRun(rep, playFrom?)`** shows the run an action produced, in place. If its id differs from `runId`, it sets `preloaded.current = rep.run.id` and navigates with `go(runPath(id))`. Either way it then calls `show(rep, playFrom)`.

`shortVersion(chunkId)` turns `"edd-policy@v4#2.1"` into `"v4 §2.1"`.

**Headline and subhead**

- **Headline:**
  - `now` mode with a replay: `With current versions, the decision becomes “{word}”.` (or `stays` when the decision didn't change);
  - paused: `report.read.headline`;
  - otherwise: `shown.read.headline`.
- **Subhead:**
  - `now` mode: `Replayed from step {k} with {shortVersion of each swap target}. Steps 1 to {k-1} were reused unchanged.`;
  - paused: `Paused at step N. Choose how to continue.`;
  - a first wrong step exists: `First went wrong at step N, when the {agent} read a replaced source. Every span still reported success.`;
  - a fork: `Forked from {parent id} at step N[ with {shortVersion of each swap}]. Steps 1 to {N-1} were reused.`;
  - otherwise: `No step read a replaced source.`

**Layout: `main.page.decision`, a 3-column grid**

1. **Left `aside.rail`**
   - Run card:
     - breadcrumb "Runs / {id}" (Runs links to `#/`);
     - `h1.h2` with the subject;
     - "KYC onboarding, run date {day}" and "{Status}, {n} evidence items, {n} claims";
     - for a fork: "Fork of {parent link} from step N ({reason})."
   - Card "Show": three checkboxes, Documents, Tool results, and "Inputs that did not drive a claim".
   - Card "Pause the run when": one `input.check-bad` checkbox per rule, labelled with the rule label. Toggling calls `api.setRule` and sets the report. A note says "Rules apply to new runs and forks of this run."
   - `section.legend`: "Current evidence", "Replaced evidence", "No source found" and "Size shows how much it drove the decision", with swatch classes `lg-ok`, `lg-bad`, `lg-warn` and `lg-size`.
2. **Centre `section.center`**
   - **`div.canvas` (dark)**
     - `canvas-head`: `h2.serif` headline and `p` subhead.
     - Controls:
       - when a replay exists, a `div.seg` with "As the agents ran it" and "With current versions". Switching modes stops play and resets `visibleStep` to the last step (switching to `now` also clears `simPause`);
       - `div.seg.seg-small` with Graph and Table. Segment buttons use `aria-pressed`.
     - `div.canvas-body` (position relative) holds `EvidenceGraph` or `ClaimsTable`, and the pause banner.
     - **Pause banner** (`div.pause-banner`, role alert), shown when `simPause` or `realPause`. It floats over the top right of the graph, as in design v2, so showing or hiding it never moves the page:
       - Title, with a pause icon: `Run paused at step N`, or `With breakpoints on, this run would pause at step N`.
       - Message: the event message, or `The {agent} retrieved a replaced source. Nothing would have been decided yet.`
       - Buttons for a real pause:
         - `btn-dark` "Swap in the current version", shown only when `suggested_swaps` exists. Calls `resume(edit, swaps)`.
         - `btn-light-line` "Approve and continue". Calls `resume(approve)`.
         - `btn-light-line` "Reject". Calls `resume(reject)`.
       - Buttons for a simulated pause:
         - `btn-dark` `"Fork with {shortVersion of each replay swap} and continue"`, for example "Fork with v4 §2.1 and continue". It calls `forkAndContinue()`, which works like design v2 and makes no request and no navigation. The automatic replay is exactly this fork (same step, same swap) and is already loaded, so it clears `simPause`, sets `mode = "now"` and calls `startPlay(replay.last_step, simStep, null, true)`. The evidence re-points from v3 to v4 on the same layout, the toggle moves to "With current versions", and steps 4 to 6 play on. If the replay is somehow not loaded, it falls back to `api.fork(run.id, simStep, report.replay.swaps, "forked at breakpoint")` followed by `openRun(result, simStep)`.
         - `btn-light-line` "Continue as it ran". Clears `simPause` and calls `play()`.
       - The real-pause actions finish with `openRun`, which shows the result in place, with no page reload:
         - "Swap in the current version" and "Approve and continue" play on from the run's `paused_at`;
         - "Reject" just shows the result.
     - **`div.scrubber`**
       - A round `button.play` with an SVG play or pause icon. Its aria-label is "Play the run step by step" or "Pause".
       - `ol.steps`, a 6-column grid, with one `button.step` per step row:
         - `done` when the step ran and `step <= visibleStep`;
         - `bad` when the mode is `run`, the run has replaced claims, and the step ran at or after the first wrong step;
         - `aria-current="step"` on the visible step;
         - contents: `span.step-bar`, `span.step-label` "N. Label", and `span.step-meta` with `"{s.toFixed(1)} s, {tokens} tok[, reused]"` or "not run";
         - clicking stops play, sets `visibleStep` and clears `simPause`.
       - `span.bp-pin` (a rotated square) marks the simulated or real pause step.
     - **`div.canvas-foot`**
       - `"{ran steps} steps, {secs.toFixed(1)} s, {tokens.toLocaleString()} tokens, {calls} model calls"`.
       - `btn-ghost-dark btn-sm` "Inspect state at step {min(visibleStep, last_step)}". It is disabled when `visibleStep < 1` and opens the `StateDrawer` for `shown.run.id`.
   - **`Branches`**: `nav.branches`, shown only when there are 2 or more items. The items are:
     - the parent ("Parent run", status);
     - "This run";
     - each fork ("Fork from step N", reason).

     Each is an `a.branch` with `"{id}, {sub}"`. The current run gets `on` and `aria-current="page"`.
   - **Tiles**, computed from `shown.counts`:
     - "Claims on current evidence": "{current} of {claims}";
     - "Built on replaced evidence": `tone-bad` if above 0, else `tone-ok`;
     - "Without a source": `tone-warn` if above 0;
     - "Retrieved but unused": "{unused} of {evidence}".
3. **Right `aside.rail-right`**. It is sticky and scrolls on its own (see section 10). Its panels change length between run, replay and fork, so the page height comes from the centre column alone and the page never jumps.
   - `AnalystRead`, using the main report when paused, else `shown`.
   - `NodeDetail`, with `selected` only if that id exists in `shown`.
   - `StabilityCard`.
   - `FeedbackCard` (keyed by run id), shown only if `shown.decision` exists.

**`ClaimsTable`** (dark table)

- Claims are sorted by step, in `div.scroll-x.table-dark-wrap`.
- Columns:
  - Claim: the name, plus the decision word or the text;
  - Agent;
  - Main source: the evidence label, the claim name, or "None found";
  - Drove: `pct` of the main share, or "—";
  - Status: `td.strong.on-dark-{status}` with the status word.

---

## 10. Styles (`frontend/src/styles.css`)

There is one plain CSS file. The header comment reads: "Light, calm shell; a dark teal 'evidence canvas' for the graph. Status colour always comes with a word or an icon."

**Tokens (`:root`)**

```
--ground #eef1ef  --surface #ffffff  --ink #13201f  --ink-2 #2a3736  --muted #5e6b6a  --line #dce2df  --line-2 #e7ecea
--canvas #0e1d21  --canvas-2 #172d33  --canvas-line #1e363c  --canvas-ink #e6eeec  --canvas-bright #f4f7f6  --canvas-muted #8fa6ab  --canvas-dim #3b575d
--bad #ff6a55  --bad-soft #ff8a78  --good #43c6ac  --warn #f2b441                       (on dark)
--bad-ink #c2412f  --bad-bg #fce9e5  --good-ink #0e7a68  --good-bg #e2f4ef  --warn-ink #8a5e00  --warn-bg #fdf2d9   (on light)
--radius 12px  --gutter clamp(16px, 2vw, 48px)  --sans "Public Sans", system-ui, -apple-system, "Segoe UI", sans-serif  --serif "Source Serif 4", Georgia, "Times New Roman", serif
```

**Base**

- `box-sizing: border-box` everywhere.
- The body uses `--ground`, `--ink` and `--sans` at 15px with line-height 1.5, `font-variant-numeric: tabular-nums` and antialiasing.
- Links are `#0e5f55`, and `#0a463f` on hover.
- `:focus-visible` gets a 2px `--good` outline with a 2px offset.
- Disabled buttons have opacity 0.6.

**Class catalog.** Values not listed here are at your discretion within the same calm style.

- **Helpers:**
  - `.row` (flex, centred), `.row.wrap`, `.row.between`, `.row.start`, `.gap-6`, `.gap-8`;
  - stacks that add top margin between children: `.stack` 20px, `.stack-4`, `.stack-12`, `.stack-16`;
  - `.min0`, `.small` (13px), `.strong` (600), `.muted`, `.muted-dark` (`--canvas-muted`), `.serif` (serif, weight 500), `.scroll-x`, `.clamp-2`;
  - tones: `.tone-bad`, `.tone-ok`, `.tone-warn` (the `-ink` colours), `.tone-bg-*`;
  - `.error` (bad-ink, 600);
  - headings: `.h2` 19px/700, `.h3` 16px/700, `.h4` 14px/700.
- **Shell:**
  - `.topbar`: flex, wrap, padding `12px var(--gutter)`, white, bottom border.
  - `.brand`: 17px/700.
  - `.topnav a`: 10px 12px padding, radius 8px, muted, 14px. With `aria-current`, it gets the ground background, ink colour and weight 600.
  - `.topbar-note`: `margin-left: auto`, muted, 13px.
  - `.page`: max-width 2560px, centred, padding `20px var(--gutter) 40px`. The page fills large screens.
  - `.card`: white, 1px line border, `--radius`. `.card.pad` adds 16px 18px padding.
  - `.card-head`: flex, between, 16px 20px padding, bottom border `--line-2`.
- **Controls:**
  - `.btn`: min-height 44px, padding 0 16px, radius 8px, 14px/600.
  - Variants: `.btn-sm` (36px), `.btn-light` (canvas-bright on canvas), `.btn-dark` (canvas, white text), `.btn-light-line` (white, border `#c9d2cf`), `.btn-ghost-dark` (transparent, canvas-ink, border `#2f4e56`), `.btn-quiet`.
  - `.chip`: pill, min-height 36px, border `#c9d2cf`, 13px/600. `.chip.on` is ink-filled with white text.
  - `.field input`: 40px tall.
  - `.check`: flex, 36px minimum. Its 18px checkbox uses `accent-color: --canvas`, and `.check-bad` uses `--bad-ink`.
  - `.table`: 14px. `th` is 12.5px, muted, 600. `td` has 14px 12px padding and a top border. The first column gets 20px left padding. `.compact` uses 8px padding.
- **Overview:**
  - `.attention`: flex-wrap, gap 28px 40px, padding 28px, radius 16px, canvas background.
    - `h1` is `clamp(34px, 1.9vw, 44px)`/1.15 in canvas-bright (27px under 720px); `p` is canvas-muted.
    - `.attention-lead` is `flex: 1 1 340px`, max-width `clamp(500px, 30vw, 680px)`, a 14px gap column.
  - `.ranked`: `flex: 1 1 460px`. Each `li` is a grid `24px 1fr auto` with a top border in canvas-line. `.ranked-tag` is a pill: `.bad` uses bad-soft on `rgba(255,106,85,.12)`, `.warn` uses warn on `rgba(242,180,65,.12)`.
  - `.tiles`: a 4-column grid with a 12px gap (2 columns under 720px). `.tile` has 14px 16px padding. `.tile-value` is 24px/700.
  - `.split` is a flex-wrap container: `.grow` is `flex: 999 1 640px` and `.side` is `flex: 1 1 clamp(300px, 22vw, 460px)`.
  - `.timeline li`: an 8px bad-ink dot drawn with `::before`, and a 1px connector line drawn with `::after`.
  - `.health`: 8px tall, 120px wide, 2px gaps. `.h-ok` is good-ink, `.h-bad` is bad-ink, `.h-warn` is `#e3b04b`.
- **Decision page:**
  - `.decision`: grid `clamp(240px, 13vw, 300px) minmax(0,1fr) clamp(320px, 19vw, 440px)`, gap `clamp(20px, 1.2vw, 28px)`, so the rails and canvas grow with the screen. Under 1180px it becomes one column, with the rails ordered after the centre.
  - `.legend` swatches are 14px circles:
    - `.lg-ok`: good-bg fill, good-ink border;
    - `.lg-bad`: bad-bg fill, bad-ink border;
    - `.lg-warn`: dashed `#b07c00` border;
    - `.lg-size`: line colour.
  - `.canvas`: canvas background, radius 16px. `.canvas-head` has 22px 24px 6px padding. `.canvas-title` has max-width `clamp(520px, 40vw, 820px)`, and its `h2` is `clamp(27px, 1.5vw, 34px)` in canvas-bright, with `min-height: 2.4em` (two lines), so a shorter or longer headline never moves the graph. Its `p` is 13.5px canvas-muted.
  - `.rail-right`: `position: sticky; top: 16px; max-height: calc(100vh - 32px); overflow-y: auto; padding: 2px; margin: -2px; scrollbar-width: thin`. Under 1180px it becomes static with no max-height.
  - `.seg`: canvas-2 background with a `#24414a` border. Buttons are 38px, `#b9cacc`. Pressed buttons are canvas-bright with canvas-coloured text. `.seg-small` buttons are 32px.
  - `.canvas-foot`: 13px canvas-muted.
- **Graph:**
  - `.graph-stage`: `transform-origin: 0 0`, with a dot-grid background `radial-gradient(#1b3239 1px, transparent 1px)` at 20px.
  - `.col-head`: top 18px, 12px canvas-muted, centred.
  - `.edges`: `pointer-events: none`. Each `.edges g` fades in when it mounts (`edge-in`, .5s from opacity 0), so edges that appear after a fork come in softly.
  - Edge colours:
    - `.edge-drove`: `#4e6d73`;
    - `.edge-context`: canvas-dim, solid, opacity .8;
    - `.edge-nosource`: warn, dash 4 5;
    - `.edge-bad`: bad at .6;
    - `.edge-path`: `.bad`, `.good` or `.neutral` (`#9fb4b8`);
    - `.edge-replaces`: good, dash 4 4.
  - `.edge-flow`: stroke-width 2.5, dash `3 11`, animation `flow` (1.1s linear infinite, `stroke-dashoffset: -28`). Colours: `.bad` `#ffd2c9`, `.good` `#c9f2e8`, `.neutral` canvas-ink at .7.
  - `.is-hidden` has opacity .08, or .04 on `g` elements. Opacity transitions take .4s.
  - `.node` and `.node-wrap` also transition `left`, `top`, `width` and `height` over .45s, so nodes move and resize smoothly between a run and its fork.
  - `.node`: absolute, 2px border. `.dot` has radius 50%. `.decision` has a 2.5px border. `.pill` has radius 10px, a 1.5px border, 6px 10px padding, and a flex column.
    - `.pill-top`: 10.5px muted. `.pill-text`: 12px, clamped to 2 lines.
    - `.is-selected`: double ring `0 0 0 3px canvas, 0 0 0 5px canvas-bright`.
  - Node statuses:
    - `.n-current`: good border, `rgba(67,198,172,.16)` fill;
    - `.n-replaced` and `.n-retired`: bad border, `rgba(255,106,85,.2)` fill;
    - `.n-nosource`: warn dashed border, `rgba(242,180,65,.08)` fill;
    - `.n-not_retrieved`: dashed `#5e7a80` border, transparent;
    - `.n-swapped_out`: `#3a5359` border, `rgba(255,255,255,.03)` fill, and its label at opacity .6 (`.node-wrap:has(.n-swapped_out) .dot-label`).
  - `.dot-label`: 196px wide, 11.5px, `#b9cacc`, with `.dot-title`, `.dot-note`, `.bad` and `.good` variants. `.decision-label` is 140px, centred, 12.5px/600.
  - `.canvas-body`: `position: relative`.
  - `.pause-banner`: absolute, `top: 8px; right: 20px; z-index: 2; width: min(420px, 100% - 40px)`, 16px padding, radius 12px, canvas-bright background, shadow `0 16px 40px -12px rgba(0,0,0,.6)`. It fades in (`card-in`, .25s, from opacity 0 and 6px up).
    - Its `p` has margin `8px 0 12px` at 13.5px. Its `.btn`s are 40px tall, 0 14px padding and 13px, so both fit on one row.
    - `.pause-title` is 13px/700 bad-ink with an SVG fill.
    - Under `prefers-reduced-motion`, `.pause-banner` and `.edges g` do not animate.
- **Scrubber:**
  - `.scrubber`: flex, top border in canvas-line.
  - `.play`: a 44px round canvas-bright button.
  - `.steps`: a 6-column grid (3 under 720px).
  - `.step-bar`: 4px tall, `#22393f`. It turns good when `.done`, and bad when `.done.bad`.
  - `.bp-pin`: a 10px bad square rotated 45°, with a canvas border, at left -5px.
- **Dark table:**
  - `.table-dark`: canvas-ink, with `th` in canvas-muted and `td` borders `#22393f`.
  - Status colours: `.on-dark-current` good, `.on-dark-replaced` bad-soft, `.on-dark-nosource` warn.
- **Branches:** `.branch` is a 10px-radius bordered card. `.on` adds an ink border plus an inset ring.
- **Right panels:**
  - `.read`: serif 17px.
  - `.source-chip`: ground background, 12px.
  - `.status-chip`: tone variants `.tone-ok`, `-bad`, `-warn` and `-quiet`, each on its `-bg` colour.
  - `.quote`: serif 15.5px with a 2px left border, plus `.tone-border-*`.
  - `.bars` and `.bar`: a 6px track. Fills: `.fill-ok`, `.fill-bad` (both `!important`) and `.fill-ink`.
  - `.facts`: a 2-column grid with a top border.
  - `.stack-bar`: 10px tall, rounded.
- **Drawer:**
  - `.drawer-backdrop`: fixed, `rgba(14,29,33,.35)`, right-aligned, z-index 10.
  - `.drawer`: `min(520px, 100%)` wide, full height, scrolls, 24px padding, left shadow.
  - `.list li`: flex with a 10px gap.
  - `.diff-add`: 20px good-bg square.
  - `.code`: ground background, 12px.
- **Reduced motion:** under `prefers-reduced-motion: reduce`, `.edge-flow` stops animating and all transitions are removed.

Design rules: status colour always comes with a word or an icon, never colour alone. The style stays calm and serious, with no playful elements.

---

## 11. Non-code assets (copy as is; not regenerated from this spec)

- `design/v1/*.dc.html` and `design/v2/*.dc.html`: HTML design references. `CLAUDE.md` describes each one.
- `CLAUDE.md`: product decisions and context.
- `docs/observability-gaps.md` and `Supersede Decision Provenance for AI Agents.{md,docx}`: concept notes.
- `frontend/package-lock.json`: regenerated by `npm install`.

---

## 12. Expected demo results (mock model, fresh in-memory store)

Use these to check a rebuild beyond the unit tests. Durations and token counts come from the simulated clock and `len // 4` token counting, so they are deterministic. If a rebuild differs here, the prompt wording or the simulated-time formulas differ from the spec.

**KYC-2041 (Meridian Ledger LLC)**

- Run: completed. Finding `confirmed_by_replay`. Decision `approve`. 106 days out of date.
- Counts: claims 5, current 2, replaced 2, nosource 1, evidence 4, unused 0.

| Claim | Status | Text | Drove (share) |
|---|---|---|---|
| c1 | current | Registration documents match the state business registry. | ev:tool:registry_lookup (1.0) |
| c2 | current | Two beneficial owners were screened against sanctions lists with no matches. | ev:tool:sanctions_screen (1.0) |
| c3 | replaced | Digital asset custody is not on the EDD escalation list. | ev:edd-policy@v3#2.1 (1.0) |
| c4 | replaced | Risk score 22 of 100 (low), so no enhanced due diligence is needed. | c3 (0.428), ev:risk-guide@v2#1 (0.572) |
| c5 | nosource | Expected monthly volume fits the stated business size. | none |
| decision | replaced | Approve account. Low risk, no enhanced due diligence required. | c4 (1.0) |

- Decision path: `['decision', 'c4', 'ev:risk-guide@v2#1', 'c3', 'ev:edd-policy@v3#2.1']`.
- Replay: approve → escalate. Changed claims: c3, c4 and decision. The replay's c3 is `Digital asset custody is a virtual asset service provider, which requires EDD under EDD Policy v4 §2.1.` and its c4 is `Risk score 71 of 100 (high), so enhanced due diligence is required.`
- Stability: `{approve: 6, escalate: 4}`, agreement 0.6. The replay run's stability is `{escalate: 10}`.
- Read headline: `Approved on a policy retired 106 days earlier.`
- Read text: `The decision rests on claim 04, which rests on claim 03, which rests on EDD Policy v3 §2.1. That version stopped applying on 1 Jul 2026. Replaying with EDD Policy v4 §2.1 changes the decision from approve to escalate. The decision is unstable: 6 approve, 4 escalate out of 10 samples.`
- Steps (seconds, tokens): 1 (1.36, 81), 2 (1.46, 82), 3 (1.26, 116), 4 (1.13, 119), 5 (0.97, 68), 6 (1.16, 147).

**KYC-2040, KYC-2039 and KYC-2033**

- All three complete with decision `approve` and finding `outcome_unchanged`. The replay keeps the decision at approve and changes no claims.
- Headline: `Used a policy retired 106 days earlier, but the outcome holds.` KYC-2033 says 105 days, because its run date is 2026-10-14.

**KYC-2036 (Tidewater Coin Exchange)**

- Paused at step 3 by `stale_evidence`. Finding `claim_used_replaced`. Days 105. Counts: claims 3, replaced 1, unused evidence 1.
- An automatic replay fork with breakpoints off reaches `escalate`.
- Read headline: `Run paused at step 3. Nothing has been decided yet.`
- Read text: `The Risk agent retrieved EDD Policy v3 §2.1, which was replaced on 1 Jul 2026. Continuing with the current version leads to: escalate.`
- `resume("edit")` creates a fork that pauses at step 6 with `ungrounded_before_action`. Its message is `Claim 05 has no source in the agent's context, and the next step (decide) cannot be undone.`

**Overview**

- Totals: `{runs: 5, paused: 1, used_replaced: 5, decision_affected: 1, unsourced_claims: 4, runs_with_unsourced: 4}`.
- Ranked: `KYC-2041, KYC-2036, KYC-2033, KYC-2039, KYC-2040`.
- Replaced: one entry, `EDD Policy v3 §2.1 → EDD Policy v4 §2.1` on `1 Jul 2026`, kind `document`, used by all 5 runs.

**Retrieval**

- The step-3 query over edd-policy and risk-guide with `top_k=2` returns `[("edd-policy@v3#2.1", 7.8018), ("risk-guide@v2#1", 2.1979)]`.

---

## 13. Build order

1. **Data and storage:** `util.py`, `store.py`, `knowledge.py` and the two JSON files. Check: `KnowledgeTests` pass.
2. **Model and tracing:** `llm.py` and `tracing.py`.
3. **Runtime:** `runtime.py`. Then `demo/kyc.py`, with the workflow and the mock script.
4. **Rules:** `rules.py`. Check: the `BreakpointTests` that only use the runner (tool loop, budget).
5. **Analysis:** `provenance.py`, then `service.py`. Check: all 22 tests pass, and the section 12 values match.
6. **APIs:** `api/app.py` and `api/stdlib_server.py`. Check: `GET /api/overview` matches section 12.
7. **Frontend foundations:** config files, `types.ts`, `api.ts`, `format.ts`, `router.ts`, `layout.ts` and `styles.css`.
8. **Frontend screens:** `Header`, `EvidenceGraph`, `Panels`, `StateDrawer`, `Overview`, `Decision`, `App` and `main`. Check: `npm run typecheck` passes. Then walk through the README's demo script against the running backend:
   - Overview: the attention band shows "1 decision rests on a retired policy."
   - KYC-2041: the coral path is visible. Play pauses at step 3. "With current versions" shows Escalate to EDD.
   - KYC-2036: edit, then the run pauses before the decision, then approve gives escalate.
9. **Docs:** both READMEs.

**Run commands (Windows)**

```powershell
cd D:\Projects\agent_rca\backend
python -m pip install -r requirements.txt
python -m uvicorn api.app:app --reload --port 8000     # or: python -m api.stdlib_server
python -m unittest discover -s tests -v

cd D:\Projects\agent_rca\frontend
npm install
npm run dev                                            # http://localhost:5173
```

The SQLite file `supersede.db` is created in `backend/` and is git-ignored. To start over, delete it, or press "Reset demo data" on the Runs page.

---

## 14. Quirks to keep (or fix on purpose)

Keep these unless you also change the dependent code and tests.

1. **Reports create replay forks.** Analysing any run that read a retired chunk creates a child run with `fork_reason = "replay with current versions"` and `breakpoints: false`. Later reports reuse that child. Top-level lists hide forks.
2. **Fork events live on the parent.** A fork's `forked` event is stored on the parent run. Paused KYC-2036 therefore shows a `forked` event from its automatic replay.
3. **Rejected runs never replay.** `_replay` only runs for `completed`, `paused` and `forked` runs.
4. **`decision_used_replaced` is rare.** It only appears when no replay was made, for example `replay=False` or a rejected run. It shares the "A claim rests on…" text with `claim_used_replaced`.
5. **Unknown customer id gives a 500.** `start_run` with an unknown `customer_id` raises `StopIteration` from `next()`.
6. **Approving keeps `pause_reason`.** On approve, `pause_reason` is not cleared; only `paused_at` is reset.
7. **Report cache key.** The analysis cache is keyed only on `(status, paused_at)`. Feedback and rule toggles don't invalidate it, which is fine because `report()` re-adds events, feedback, forks and rules on every call.
8. **`StepContext.retrieve` writes excluded evidence.** It still writes excluded chunks into state evidence and only hides them from the step's own use. `score_risk` filters its own evidence lookup by `exclude` for the same reason.
9. **Silent tracers still count model calls.** They count calls but store nothing, so leave-one-out and sampling never write spans.
10. **The Header link is hard-coded.** "Decision graph" always points at `#/runs/KYC-2041`.
11. **`api.fork` never sends `guard`.** The frontend doesn't use guard mode; it is only reachable through the API and the tests.
12. **No duplicate forks.** React StrictMode runs `load()` twice in dev, and two tabs can ask for the same report at once. The service lock and fork reuse together keep a run at one replay and one fork per distinct (step, options).
