# Supersede: Decision Provenance for AI Agents

Oct 15, 2026 · @Hemanth

## Summary

Supersede answers "why did the agent say this?" one claim at a time: the evidence that actually drove each claim, which document version it came from, whether that version has since been replaced, which agent or step first went wrong, and what the answer would be with current information.

Existing tracers (LangSmith, Langfuse, Phoenix, Datadog, MLflow) show *what ran*. None of them natively show which source drove a claim or whether that source was still valid. That gap is real, documented in research, and buildable in 1–2 days on top of OpenTelemetry.

- **Name:** Supersede: Why-Trace for Agents (alternatives: Because, Rootline)
- **Track:** Agentic Development
- **Pitch:** explanations backed by evidence, not by the agent's own story
- **Demo domain:** US banking processes with synthetic data, led by a KYC onboarding scenario

## What today's tools show, and what they don't

Current tools are strong on spans, tool calls, tokens and handoffs, but none natively attribute claims to sources, track document versions, or replay with different evidence.

| Tool | What it shows today |
| --- | --- |
| OpenTelemetry GenAI conventions | Standard spans for chat, retrieval, tool calls and agent invocations; still experimental, no 1.0 |
| LangSmith | Native LangChain/LangGraph traces, step-through debugging, LLM clustering of failures |
| Langfuse | Nested traces, prompt management, evals, inferred agent graphs; open-source core |
| Arize Phoenix | OpenInference spans; retriever spans record document IDs, scores and content |
| Datadog | Execution graph of tool calls and handoffs, correlated with infrastructure monitoring |
| MLflow Tracing | One-line autolog across 30+ frameworks, token and cost tracking |
| W&B Weave, Braintrust, AgentOps | Trace trees, eval scoring, AI-assisted debugging, session replay |

**What none of them do natively:**

1. **Claim-level attribution.** They list what was retrieved, not which document drove a specific sentence.
2. **Evidence version status.** No tool knows Policy v3 was replaced by v4, so every span stays green while the answer is wrong.
3. **Root cause across handoffs.** Handoff graphs exist, but nothing says which agent or step introduced the error.
4. **Counterfactuals.** You can replay with a different model, not with different evidence.
5. **Reasoning provenance.** An Oracle research paper argues observability covers the mechanical layer but lacks queryable records of why each action was chosen.

LangChain's 2025 survey of 1,340 practitioners found 89% have observability, yet quality is still the top production barrier (32%). Teams can see what happened, not why it was wrong.

## Why agent explanations can't be trusted on their own

An agent's own explanation is unreliable, so Supersede must show verified evidence beside it, never instead of it.

| Finding | Number | Source |
| --- | --- | --- |
| Reasoning models mention the hint that actually drove their answer | 25% (Claude 3.7 Sonnet), 39% (DeepSeek R1) | [Anthropic](https://www.anthropic.com/research/reasoning-models-dont-say-think) |
| RAG citations that are post-rationalized, worst case | up to 57% | [Wallat et al.](https://arxiv.org/pdf/2412.18004v1) |
| Best method finding the decisive failing step in multi-agent runs | 14.2% (53.5% for the agent) | [Who&When](https://arxiv.org/pdf/2505.00212) |
| Step attribution with full traces vs output-only logs | 30% vs 17% | [TraceElephant](https://arxiv.org/pdf/2606.08162) |
| Correct answers flipped by outdated retrieved documents | 30% (Llama), 37% (Qwen) | [Stale-Document Poisoning](https://arxiv.org/html/2609.31342) |
| Split-brain hallucinations with a SUPERSEDES graph vs vector RAG | 0% vs 70% (50 synthetic episodes) | [EngramRAG](https://arxiv.org/html/2609.32049) |

Multi-agent failures are mostly systemic: specification and design (42%), inter-agent misalignment (37%) and missing verification (21%), per the [MAST study](https://arxiv.org/abs/2503.13657). Handoffs are where errors spread.

Auditability is also becoming a requirement. The EU AI Act's Article 86 gives people affected by high-risk decisions a right to explanation, and banks already face audit and fair-lending explanation duties.

## Techniques behind the trace

Six existing techniques combine into one pipeline, each in a hackathon-sized version.

| Technique | What it gives | Hackathon version |
| --- | --- | --- |
| Context attribution ([ContextCite](https://www.themoonlight.io/en/review/contextcite-attributing-model-generation-to-context)) | Which retrieved chunk *caused* a claim | Leave-one-out over 3–5 chunks per claim; label "drove" vs "supports" |
| Claim checks | Whether a source backs a claim | LLM splits answer into claims, then an entailment check per chunk |
| Supersession graph ([EngramRAG](https://arxiv.org/html/2609.32049)) | Whether evidence is still current | SUPERSEDES edges between document versions; status badge on each claim |
| Provenance graph ([PROV-AGENT](https://www.researchgate.net/publication/396287616_PROV-AGENT_Unified_Provenance_for_Tracking_AI_Agent_Interactions_in_Agentic_Workflows)) | Standard export for auditors | Claims, chunks and versions as entities; steps as activities; export PROV-JSON |
| Failure attribution ([AgenTracer](https://arxiv.org/html/2509.03312v2)) | Which agent and step first went wrong | LLM judge picks the agent, then checks its steps one by one |
| Counterfactual replay | Proof of the cause | Swap the superseded chunk for the current one, re-run from that step, diff the claims |

The sequence: what did the agent claim, what drove each claim, was that evidence still valid, where did it enter and who passed it on. Replay then tests the diagnosis.

The same layer also supports standard quality metrics: claim-level faithfulness, context relevance (retrieved chunks that drove nothing), answer relevance, and consistency across repeated runs.

## UX for non-engineers

Start from the answer, not the trace: evidence sits beside each claim, and the full graph opens only on demand.

- **Evidence next to the claim.** [NN/g research](https://www.nngroup.com/) found people rarely click citation links, so place sources beside the sentence they support.
- **Reveal on demand.** Answer first, then "Why?", then the evidence card, then the graph.
- **Separate the agent's story from verified evidence.** Self-reported reasoning in grey italics; verified evidence as solid cards with attribution strength.
- **Plain status words:** Based on, Replaced by, Not supported, First went wrong at. Always pair colour with an icon.

**Views to build**

1. **Answer view:** claims highlighted green (current evidence), amber (superseded), red (unsupported).
2. **Evidence card:** claim, source title and version, quote, a drove/supports strength bar, status ("Replaced by v4 on 1 Jul 2026").
3. **Derivation graph:** claim back to chunk, document version, retrieval step and agent, with the newer version on a dashed SUPERSEDES edge.
4. **Swimlane timeline:** one lane per agent, a pin on the first wrong step.
5. **Replay diff:** original and replayed answers side by side, changed claims highlighted.
6. **Audit packet:** a one-page summary plus a PROV-JSON appendix.

## Refined concept

Submit under Agentic Development: that track describes software as code, prompts, tool orchestration, retrieval and model outputs, and the derivation graph connects exactly those pieces for every claim.

**Features by priority (1–2 day build)**

| Priority | Feature | When |
| --- | --- | --- |
| P0 | Instrumented two-agent demo emitting OpenTelemetry spans with chunk IDs and document versions | Day 1 |
| P0 | Versioned document store with SUPERSEDES edges | Day 1 |
| P0 | Claim attribution: claim splitting, leave-one-out, entailment check | Day 1 |
| P0 | Evidence-card UI with inline claim highlights and version status | Day 1 |
| P1 | Derivation graph and swimlane, filtered to the selected claim | Day 2 |
| P1 | Replay with current truth, plus diff view | Day 2 |
| P1 | First-wrong-step pointer, labelled "suspected" and confirmed by replay | Day 2 |
| P2 | Guard mode: block superseded chunks before generation | If time |
| P2 | Audit packet export (PDF + PROV-JSON) | If time |
| P2 | Quality strip: faithfulness, relevance, consistency | If time |

**Architecture**

Agents send OpenTelemetry spans through a collector to a provenance builder, which reads the version graph and feeds the replay service and the UI.

&#91;embedded content: Supersede architecture · 6 components\]

The version store serves both the agents' retrieval and the builder's status check, so the same graph that blocks stale chunks also explains them.

**How it differs from Langfuse and LangSmith**

They show what ran; Supersede shows why the answer came out that way and whether that reason still holds. Position it as a layer that reads their traces, not a replacement.

|  | LangSmith / Langfuse | Supersede |
| --- | --- | --- |
| Unit of analysis | The trace (spans) | Each claim in the answer |
| Sources | What was retrieved | What actually drove each claim |
| Document versions | Not tracked | Flags superseded evidence |
| Root cause | You read the trace | Points to the agent and step |
| Proving a fix | Re-run with another model or prompt | Replay with corrected evidence and diff |
| Audience | Engineers | Engineers, business users, auditors |

Where they are stronger: maturity, scale, open-source tooling, prompt management, datasets and cost tracking. Say they don't do this "natively", not that they "can't", and check their docs before the event.

## Banking demo scenarios

Lead with KYC onboarding: a wrongly approved high-risk customer is a compliance failure every bank judge understands. Use the chatbot as a 30-second opener and the rest as a cross-domain closing slide.

| Scenario | Agents | Outdated document | What goes wrong | What Supersede shows |
| --- | --- | --- | --- | --- |
| **KYC onboarding (main demo)** | Document agent, Risk agent, Decision agent | Enhanced Due Diligence Policy v3 (v4 adds crypto-related businesses to escalation) | Risk agent retrieves v3, scores low risk; account auto-approved | Claim driven by v3 §2.1, replaced by v4; first wrong at Risk agent retrieval; replay gives "Escalate to EDD review" |
| **Customer service chatbot (opener)** | Single chatbot | Fee Schedule 2025 (replaced by 2026) | Quotes last year's overdraft fee or dispute window | Fee claim traced to the 2025 schedule; replay gives the correct fee |
| **Loan underwriting** | Intake agent, Underwriting agent | Credit policy with max DTI 43% (fictional change to 40%) | Applicant at 42% DTI approved | Rule that drove approval and the step that used it; claim-level reasons suit adverse action notices |
| **AML alert triage** | Triage agent, Investigator agent | Old investigation runbook | Alert closed as false positive; earlier PEP note retrieved but ignored | Two root causes: outdated runbook, and a relevant chunk that drove nothing |
| **Branch manager scorecard (data pipeline)** | Reporting agent | Data dictionary: "Active Customer" v1 (login in 90 days) vs v2 (transaction in 60 days) | Branch 12 shows 18% growth in active customers | Claim traced to metric v1; replay with v2 shows 6% growth |

**Synthetic data rules**

- Use a fictional bank name and synthetic customers (the Python library Faker works well). Never use real customer data, even masked.
- Write fictional internal policy documents with clear version numbers and dates.
- Keep changes as internal policy updates, not claims about real regulation changes.
- Label every screen "Synthetic data".

## Beyond documents: any kind of evidence

Supersede must not depend on versioned documents. Any input that shapes a claim is evidence, and each kind of evidence has its own validity check; document versioning is just one of them.

The core loop stays the same: claim, origin, validity check, path to decision, replay.

| Origin of the claim | How it is traced | How it is checked |
| --- | --- | --- |
| Data (SQL query result) | Match the number in the answer to the cell in the query result | Table freshness, filters, joins, certified metric definition |
| Tool output (API, calculator, model) | Tool span inputs and outputs | Correct call, errors, timeouts |
| Another agent | Handoff span between agents | Follow it back to that agent and check its origin |
| Document | Retrieved chunk IDs | Version and supersession |
| User input or instructions | Prompt span | Followed or ignored |
| Model's own knowledge | Nothing in context explains it | Cannot be sourced: flagged as ungrounded, tested for consistency across runs |

**Data chatbot on Databricks (text-to-SQL).** A manager asks for last quarter's overdraft fee revenue and gets $4.2M. Supersede links the number to the exact cell in the query result and the query to its tables. Checks show the table was refreshed 9 days ago, the query used calendar instead of fiscal quarter, and it used gross fees instead of the certified net fee revenue definition. Replay with the certified definition and correct quarter shows $3.7M. Attribution here is deterministic: numbers are matched to cells, no LLM needed.

**Data transformation agent.** The agent writes a pipeline step that creates `active_customer`. Evidence is the input schema, the generated code and row counts before and after. Column-level lineage shows which step introduced 12,000 nulls or duplicated rows; replay reruns that step with the fix and compares row counts and distributions.

**Agents working from each other's context and general knowledge.** Each message between agents is evidence. Supersede follows a claim back hop by hop until it reaches data, a tool, a document or nothing. Leave-one-out on upstream messages shows which agent's input drove the decision. A trail that ends in the model's own knowledge is labelled ungrounded, checked for stability across 5 runs, and optionally verified with a tool or a second model.

**Product impact**

- Document versioning becomes one plug-in check among data freshness, metric definitions, schema changes, tool errors, agent handoffs and ungrounded claims.
- The name still fits: definitions, schemas and data snapshots get superseded too, not only policies.
- For the hackathon, keep KYC as the main demo and add one short text-to-SQL example to prove the idea is general.
- State the limit in the pitch: claims from the model's own knowledge get no source, only an ungrounded flag and a consistency test.

## Demo script (5 minutes)

1. **0:00–0:30, the problem.** The chatbot quotes last year's overdraft fee. Every trace is green. Show one number: outdated documents flip 30–37% of otherwise-correct answers.
2. **0:30–1:15, before.** Run the KYC onboarding flow. Show the raw span tree: all spans succeeded, tools called, latency fine. "This shows what ran, not why the decision is wrong."
3. **1:15–2:30, the moment.** Click the amber claim "Low risk, no EDD required." The evidence card shows it was driven by EDD Policy v3 §2.1, replaced by v4. The graph lights the path; a pin marks the Risk agent's retrieval step. The agent's own narrative sits beside it in grey and says something different.
4. **2:30–3:30, proof.** Click "Replay with current truth." v4 replaces v3, the run restarts from that step, and the diff shows the decision flip to "Escalate to EDD review."
5. **3:30–4:15, fix and governance.** Turn on guard mode and rerun: the stale chunk is blocked and logged. Export the audit packet.
6. **4:15–5:00, close.** One slide with lending, AML and the manager scorecard: same layer, any OpenTelemetry trace.

## Recommendations

- Build only the core loop (claim, evidence, outdated version, replay) on the KYC scenario, and make it excellent.
- Script the failure on purpose: make v3 rank higher so the demo fails reliably. Pre-cache the replay so it runs in under 10 seconds.
- Put your design effort into the evidence card and the diff. Test both on a non-engineer before the event.
- Call the first-wrong-step output a "suspected root cause" and confirm it by replay.
- Check who is judging. Product-leaning panels need a stronger cost story ("this approval would have cost $X").

## Caveats

- Several sources are 2026 preprints that haven't been peer-reviewed, including EngramRAG (synthetic episodes) and Stale-Document Poisoning. Present their numbers as reported results.
- Competitor features change monthly; some comparisons come from vendor blogs.
- The 57% citation figure is an adversarial worst case; the 25% and 39% figures are for specific hint setups.
- Leave-one-out attribution only measures influence among retrieved context, not the model's trained knowledge.

## Sources

- [Anthropic: Reasoning models don't always say what they think](https://www.anthropic.com/research/reasoning-models-dont-say-think)
- [Wallat et al.: Correctness is not Faithfulness in RAG Attributions](https://arxiv.org/pdf/2412.18004v1)
- [Who&When: automated failure attribution](https://arxiv.org/pdf/2505.00212)
- [AgenTracer](https://arxiv.org/html/2509.03312v2)
- [TraceElephant](https://arxiv.org/pdf/2606.08162)
- [MAST: Why do multi-agent LLM systems fail?](https://arxiv.org/abs/2503.13657)
- [Stale-Document Poisoning](https://arxiv.org/html/2609.31342)
- [EngramRAG](https://arxiv.org/html/2609.32049)
- [Agent Execution Record (Oracle)](https://arxiv.org/pdf/2603.21692)
- [ContextCite review](https://www.themoonlight.io/en/review/contextcite-attributing-model-generation-to-context)
- [Langfuse Agent Graphs](https://langfuse.com/docs/observability/features/agent-graphs)
- [Datadog: Monitor AI agents](https://www.datadoghq.com/blog/monitor-ai-agents/)
- [MLflow Tracing](https://mlflow.org/docs/latest/genai/concepts/trace/)
- [OpenTelemetry GenAI conventions in 2026](https://dev.to/gabrielanhaia/opentelemetry-genai-semantic-conventions-your-llm-traces-should-look-like-this-in-2026-3ff6)
