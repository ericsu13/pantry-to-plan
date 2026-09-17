# Single Agent + MCP Implementation Readout

## Outcome

The application now supports two user-selectable planning modes:

- **Standard planner** — the original Python-orchestrated planner.
- **Agent + MCP planner** — one model-controlled tool loop over a local MCP
  server, followed by mandatory deterministic validation.

Multi-agent orchestration is intentionally out of scope for this increment.

## Agentic boundary

The single agent decides which tool to call, which candidates to investigate,
which grounded recipe IDs to order, whether a simulation should be revised,
and when to request final approval. Python retains authority over the confirmed
pantry and request, recipe facts, vegetarian eligibility, scoring, depletion,
shopping arithmetic, execution limits, and final validation.

The controller overwrites the pantry and request on every applicable model
tool call with the authoritative application values. A model therefore cannot
turn off `vegetarian_required` or change inventory quantities through its tool
arguments.

## MCP tools

| Tool | Existing code reused |
|---|---|
| `search_recipes` | `retrieval.py` |
| `get_recipe_details` | `repository.py` and `recipes.py` |
| `evaluate_candidates` | `constraints.py` and `scoring.py` |
| `simulate_plan` | `pipeline.py` and `inventory.py` |
| `validate_final_plan` | Deterministic proposal materialization and all hard gates |

The MCP transport is local `stdio`. `meal_tools_client.py` starts and closes the
server automatically for each agent run.

## New files

- `mcp_models.py`
- `meal_tools_server.py`
- `meal_tools_client.py`
- `mcp_planner_agent.py`
- `evaluation/run_mcp_agent_eval.py`
- `evaluation/datasets/mcp_agent_expectations_v1.json`
- `tests/test_mcp_tools.py`
- `tests/test_mcp_agent.py`
- `tests/test_app_services_agent.py`

## Modified files

- `app.py` — planning-mode selection, visible trace, and grounded meal reasons.
- `app_services.py` — MCP-agent construction, routing, and safe fallback.
- `pipeline.py` — reusable deterministic agent-proposal materializer and
  expanded retrieval before declaring a false no-result.
- `config.py` — MCP model, timeout, tool-call, and revision limits.
- `evaluation/evaluators.py` — explicit cross-cuisine-relaxation check.
- `evaluation/fakes.py` — reproducible tool-result-driven decision model.
- `README.md` and `evaluation/README.md` — operation and evaluation guidance.
- `pyproject.toml`, `requirements.txt`, and `uv.lock` — official Python MCP SDK.

## Run locally

```bash
cd /Users/shriramvaidya/Backup/terminus/mavenlearning/groupproject/pantry-to-plan-main
uv sync --locked
uv run streamlit run app.py
```

Set `OPENAI_API_KEY` to make **Agent + MCP planner** available. Pinecone remains
optional because the MCP search tool uses the existing automatic TF-IDF
fallback.

## Verification

```bash
uv run python -m unittest discover -s tests -v
uv run python -m evaluation.run_mcp_agent_eval
```

Verified results for this implementation:

- 64 automated tests passed.
- 23/23 deterministic golden cases passed.
- 23/23 single-agent MCP golden cases passed over the real stdio transport.
- Streamlit started successfully in headless smoke testing.

The live model-controlled path requires the user's OpenAI credentials and is
therefore covered structurally through an injectable deterministic decision
model; the MCP transport and all five real tools are exercised end to end.
