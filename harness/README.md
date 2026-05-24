# Harness

This directory contains repeatable checks around the agent system.

## Fast offline checks

Run these before changing prompts, routing, or state handling:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

These tests use fake chains and do not call Ollama or MySQL.

## Live router eval

Run this when changing the router prompt, model, or LLM settings:

```powershell
.\.venv\Scripts\python.exe harness\run_router_eval.py
```

The eval uses `harness/router_cases.json` and writes reports under
`harness/results/`. Generated reports are ignored by git.

## Deterministic query eval

Run this when changing `QueryAgent`, the query planner, or SQL templates:

```powershell
.\.venv\Scripts\python.exe harness\run_query_eval.py
```

This eval uses `data/sample_commands.csv` as the golden dataset. It checks
whether each query selects MySQL or Chroma correctly, whether the planned SQL
contains the expected structure, and whether the rows computed from the CSV
match the expected answer.

## DB smoke check

Run this after changing `.env` database settings:

```powershell
.\.venv\Scripts\python.exe harness\db_smoke.py
```

It checks connectivity with `SELECT 1` and does not print secrets.
