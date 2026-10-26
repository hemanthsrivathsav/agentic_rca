# Supersede: pitch notes

## The one line

> **MLflow tells you why your agent crashed. Supersede proves why your agent was wrong when nothing crashed.**

## Why it is true (three points)

1. **Silent failures, not errors.** Tracing tools (MLflow, LangSmith, Langfuse) find failures that announce themselves: a span throws, the status turns red, and an assistant reads the error. KYC-2041 never crashes. Every span is green, the answer is fluent, and it approves an account on a due diligence policy retired 106 days earlier. Supersede checks *successful* runs: was every claim backed by evidence that was valid on the run date? For a bank, a confident wrong approval is worse than a crash.
2. **Proof, not a guess.** MLflow's assistant is a model reading a trace and offering an explanation. Supersede runs experiments: it hides each input, swaps in the current version of a source, re-runs the step and compares. Click **Prove this decision**: hiding claim 04 changes the approval, hiding anything else does not, and swapping in EDD Policy v4 flips the decision to escalate. Six re-runs, nine model calls, cause confirmed.
3. **Stops it before it happens.** Tracing is after the fact. Supersede can pause a live run the moment a replaced policy enters the agent's context (KYC-2036), before anything irreversible is decided.

## What MLflow does well (do not argue with this)

From the MLflow Tracing tutorial: one-line `autolog` for 20 to 30 frameworks, spans with inputs, outputs, tokens, cost and latency, a UI with dashboards and an error filter, and the MLflow Assistant (3.9+) that reads a failed trace and suggests a root cause and fix. All three of its debugging examples are crashes: an invalid message role, a tool name with spaces, and a parser that threw an error.

Do not say MLflow "can't" do what Supersede does. Say it is not built for it.

## Positioning

A layer on top, not a replacement: "Keep MLflow for tracing. Supersede adds proof and version awareness." MLflow traces use the OpenTelemetry format, so reading them is a believable next step. At a bank on Databricks, judges may know MLflow well; this framing makes it an ally.

## Demo order (5 minutes)

1. **Runs page (30 s).** "1 decision rests on a retired policy." Every run here was marked successful by tracing.
2. **KYC-2041 (60 s).** The coral path from EDD Policy v3 (retired 106 days earlier) through claims 03 and 04 to "Approve account". "In MLflow this run is green."
3. **Prove this decision (60 s).** The experiment table. Read the verdict aloud: cause confirmed. "That is not a model explaining itself. Each row actually ran."
4. **Play (45 s).** The run rebuilds step by step and stops at step 3: "With breakpoints on, this run would pause here." Fork with v4 and continue: the evidence re-points, the decision becomes "Escalate to EDD", stability goes from 6/4 to 10/10.
5. **KYC-2036 (45 s).** A live pause. Swap in the current version, pause again before the irreversible decision (claim 05 has no source), approve, done.
6. **Close (30 s).** The one line, plus "works for any evidence type: documents, data, tools, other agents".

## Questions judges may ask

**"Isn't this just LangSmith or MLflow?"** They show what ran and explain crashes. Supersede proves which evidence drove each claim, whether that evidence was still valid, and what the decision becomes with current evidence. It reads the same kind of traces.

**"Doesn't re-running steps cost a lot?"** About 1 extra model call per input per claim, plus the replay. KYC-2041 needs 9 calls to prove the decision. Run it on flagged or high-stakes decisions (approvals, escalations), not every chat message, and cache the earlier steps (forks reuse them).

**"What if the model is not deterministic?"** That is why stability sampling exists: the decision is re-sampled 10 times. 6 approve / 4 escalate is itself a risk signal. Experiments can be repeated and averaged with a real model.

**"What about claims from the model's own knowledge?"** Supersede says so honestly: claim 05 has no source in context, so it cannot be proven from evidence, and a breakpoint stops the run before an irreversible step that depends on it.

**"Does it only work for documents?"** No. Any input that shapes a claim is evidence: query results, tool outputs, other agents' messages, user instructions. Document versioning is one validity check among several (data freshness, metric definitions, schema changes).

**"Is this a real model?"** The demo uses a scripted offline model so it is repeatable. The same prompts run on Azure OpenAI by setting four environment variables.
