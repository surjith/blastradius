# Blast Radius — PoC

A proof-of-concept demonstrating how a **semantic knowledge graph** can be the backbone of an **agentic workflow** for change-impact analysis.

The central thesis: _if your domain model is machine-readable (OWL ontology + RDF instances), a deterministic graph engine can answer impact questions reliably — and a natural-language layer can sit on top without losing correctness, because the agent is grounded in the graph, not guessing_.

---

## What this PoC demonstrates

| Capability | What it shows |
|---|---|
| **Semantic model as execution substrate** | An OWL ontology + RDF instance graph is loaded into NetworkX. Every traversal, impact analysis and scenario simulation runs against typed, connected data — not a flat schema. |
| **Deterministic impact engine** | Three operations — *blast radius* (what does this touch?), *impact analysis* (what changes if I do X?), *scenario simulation* (baseline vs. what-if delta) — produce stable, auditable results. |
| **Agentic orchestration via LangGraph** | A state machine routes natural-language or JSON envelopes through `parse → validate → execute → format` nodes. The graph engine is a tool the agent calls; the agent doesn't make up answers. |
| **NL → structured envelope → result** | OpenAI Structured Outputs produce a typed `RequestEnvelope` (intent, start URI, traversal spec, change spec, optional inline scenario). The model is grounded by a full entity/URI list in the system prompt. |
| **Inline scenario generation** | The model can generate `AttributeOverride` and `EdgeMutation` objects directly from NL ("what if Melbourne is down?") without needing a pre-written scenario file. |
| **Human-readable, grouped output** | Formatters resolve URIs to display names and group results by entity type (Customers, Orders, Fulfillments, …) with status annotations and named propagation paths. |
| **Interactive web demo** | A FastAPI + vis.js single-page app visualises the full graph, shows a grouped entity sidebar, and provides a chat window where results are highlighted live on the graph with glow effects. |

---

## Project layout

```
data/
  shopify_ontology.ttl      OWL ontology — defines entity types and object properties
  synthetic_instances.ttl   RDF instances — 5 products, 4 locations, 5 customers, 5 orders, …
scenarios/                  Pre-written ScenarioSpec JSON files (what-if deltas)
envelopes/                  Pre-written RequestEnvelope JSON files (CLI test inputs)
core/                       Graph engine (RDF loader, NX builder, blast/impact/simulate)
orchestration/              LangGraph workflow, envelope model, formatters, OpenAI interpreter
web/                        FastAPI server + vis.js SPA
agents/                     (placeholder for future sub-agents)
tests/                      131 pytest tests
main.py                     Typer CLI (blast / impact / simulate / agent / visualize / serve)
```

---

## Quick start

**Prerequisites**: Python 3.11+, [uv](https://docs.astral.sh/uv/)

```bash
# 1. Install dependencies
uv sync

# 2. Set your OpenAI key (required for NL queries; not needed for JSON envelope CLI)
cp .env.example .env          # then edit .env and set OPENAI_API_KEY
                               # optionally set OPENAI_MODEL (default: gpt-4o)

# 3. Run tests
uv run pytest

# 4. Launch the web demo
uv run main.py serve
# → open http://localhost:8000
```

**.env file**

```
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
```

---

## Web demo

The SPA at `http://localhost:8000` provides:

- **Graph pane** — full knowledge graph with colour-coded entity types; click any node to pre-fill the chat
- **Entity sidebar** — grouped, searchable entity list; click to focus + highlight
- **Chat panel** — type a natural-language question or paste a JSON envelope; affected nodes are highlighted on the graph with glow effects (gold = start node, red = impacted, amber = newly exposed, green = no longer affected)
- **Templates** — quick-start buttons for common queries

Highlighted node colours:

| Colour | Meaning |
|---|---|
| Gold | Start / focal node |
| Red | Directly impacted (blast / impact) |
| Amber | Newly exposed by scenario (simulate delta) |
| Green | No longer affected after scenario |
| Dimmed | Not in the impact set |

---

## Running tests

```bash
uv run pytest               # all 131 tests
uv run pytest -q            # quiet summary
uv run pytest tests/test_formatters.py -v
```

---

## Roadmap — MVP

The PoC establishes the core loop: _semantic model → deterministic engine → agent-callable tools → NL interface_. The MVP builds production-grade layers around that loop.

### 1 — Guided UI / no-JSON workflows
- Better UI / presentation
- Entity picker → change/scenario chooser → run → results (no manual JSON)
- Scenario library with editable forms and template management

### 2 — Robust NL layer
- Entity disambiguation (resolve partial names to URIs, surface alternatives)
- Multi-turn clarification dialogs (not single-shot)
- Guardrails: allowed predicates, entity constraints, invalid scenario prevention
- Evaluation harness + regression tests for NL parsing quality

### 3 — Multi-agent orchestration
Decompose the monolithic workflow into specialised agents with shared state:
- **Entity Resolver Agent** — fuzzy name → canonical URI
- **Scenario Builder Agent** — NL → validated ScenarioSpec
- **Impact Explainer Agent** — deterministic result → business narrative
- **Remediation Agent** — impact result → suggested corrective actions
- Traceability: every agent decision logged with its evidence

### 4 — Explanation quality
Layered output: deterministic graph result + LLM-generated business narrative:
- "Why impacted?" summary per entity type
- "Key dependency paths" narrative
- "Recommended actions" (bounded, evidence-cited)
- Citations to ontology triples / graph edges in every explanation

### 5 — Persistence and run management
- Store: graph hash, scenario inputs, results, deltas, audit logs
- Run comparison (diff between runs), history, bookmarks

### 6 — Real data ingestion
- Shopify Admin API / CSV / DB connectors
- Schema and ontology evolution handling
- Data validation + mapping layer

### 7 — Semantic inference
- OWL-RL reasoning to enrich implicit relationships
- Configurable inference on/off with test coverage (inference changes semantics)

### 8 — Engine enhancements
- Multiple paths per node with path ranking
- Pluggable, versioned severity-scoring policies
- Traversal filters: type constraints, stop conditions, edge-label allowlists

### 9 — Performance and scale
- Graph caching + incremental updates
- Target: 10⁵+ nodes/edges with sub-second traversals
- Profiling + explosion guards

### 10 — Production hardening
- AuthN/AuthZ, tenant isolation
- Structured logs, distributed traces, metrics
- Docker packaging, CI/CD pipeline
- Prompt injection resistance and security review

## CLI usage

```bash
# Blast radius — what does this node touch?
uv run main.py blast --start "https://example.com/shopify-inst#prod_mug" --depth 4 --direction both

# Impact analysis — what is affected if this relationship changes?
uv run main.py impact --change-type relationship_change --target "https://example.com/shopify-inst#prod_mug"

# Simulate a what-if scenario
uv run main.py simulate --change-type relationship_change --start "https://example.com/shopify-inst#loc_mel_01" \
  --scenario-json scenarios/outage_reroute_fulfillment.json

# Natural-language agent (requires OPENAI_API_KEY)
uv run main.py agent --message "What is the blast radius of the Ceramic Mug?"
uv run main.py agent --envelope-file envelopes/blast_prod_mug.json

# Generate pyvis HTML visualisation
uv run main.py visualize --scenario-json scenarios/remove_variant.json
```

---