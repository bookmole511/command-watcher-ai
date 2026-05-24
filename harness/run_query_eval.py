"""Evaluate QueryAgent tool selection and structured query accuracy.

The eval is deterministic and uses data/sample_commands.csv as the golden
dataset, so it does not require MySQL or Ollama.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agents.query_planner import CHROMA_TOOL, MYSQL_TOOL, QueryPlan, choose_query_plan


DEFAULT_CASES = ROOT / "harness" / "query_cases.json"
DEFAULT_DATA = ROOT / "data" / "sample_commands.csv"
DEFAULT_RESULTS_DIR = ROOT / "harness" / "results"


def load_cases(path: Path) -> List[Dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_data(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["timestamp"])


def execute_plan_on_dataframe(plan: QueryPlan, df: pd.DataFrame) -> List[Dict[str, Any]]:
    working = _apply_filters(plan, df)

    if plan.operation == "command_count_by_user":
        return _group_count(working, "user_name", "command_count", plan)
    if plan.operation == "failed_count_by_user":
        failed = working[working["exit_code"] != 0]
        return _group_count(failed, "user_name", "failed_count", plan)
    if plan.operation == "command_frequency":
        return _group_count(working, "command", "command_count", plan)
    if plan.operation == "client_ip_frequency":
        return _group_count(working, "client_ip", "access_count", plan)
    if plan.operation == "list_logs":
        columns = [
            "id",
            "user_name",
            "command",
            "timestamp",
            "current_dir",
            "client_ip",
            "server_ip",
            "exit_code",
            "session_id",
        ]
        rows = (
            working.sort_values("timestamp", ascending=False)
            .head(plan.params.get("limit", 20))[columns]
            .copy()
        )
        rows["timestamp"] = rows["timestamp"].astype(str)
        return rows.to_dict(orient="records")

    return []


def _apply_filters(plan: QueryPlan, df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()
    command_contains = plan.params.get("command_contains")
    user_name = plan.params.get("user_name")
    days = plan.params.get("days")

    if command_contains:
        working = working[
            working["command"].str.contains(command_contains, case=False, regex=False, na=False)
        ]
    if user_name:
        working = working[working["user_name"].str.lower() == user_name.lower()]
    if days:
        cutoff = df["timestamp"].max() - pd.Timedelta(days=int(days))
        working = working[working["timestamp"] >= cutoff]

    return working


def _group_count(df: pd.DataFrame, group_col: str, count_col: str, plan: QueryPlan):
    if df.empty:
        return []

    grouped = (
        df.groupby(group_col)
        .size()
        .reset_index(name=count_col)
        .sort_values([count_col, group_col], ascending=[False, True])
        .head(plan.params.get("limit", 10))
    )
    return grouped.to_dict(orient="records")


def evaluate_case(case: Dict[str, Any], df: pd.DataFrame) -> Dict[str, Any]:
    plan = choose_query_plan(case["query"])
    actual_rows = execute_plan_on_dataframe(plan, df) if plan.tool == MYSQL_TOOL else []

    checks = []
    checks.append(("tool", plan.tool == case["expected_tool"], plan.tool))
    checks.append(("operation", plan.operation == case["expected_operation"], plan.operation))

    if plan.tool == MYSQL_TOOL:
        sql = plan.sql or ""
        for expected in case.get("expected_sql_contains", []):
            checks.append((f"sql contains {expected}", expected in sql, sql))

        expected_rows = case.get("expected_rows", [])
        for index, expected_row in enumerate(expected_rows):
            if index >= len(actual_rows):
                checks.append((f"row {index}", False, None))
                continue
            actual_row = actual_rows[index]
            for key, expected_value in expected_row.items():
                checks.append(
                    (
                        f"row {index}.{key}",
                        actual_row.get(key) == expected_value,
                        actual_row.get(key),
                    )
                )

    passed = all(item[1] for item in checks)

    return {
        "id": case["id"],
        "query": case["query"],
        "passed": passed,
        "expected_tool": case["expected_tool"],
        "actual_tool": plan.tool,
        "expected_operation": case["expected_operation"],
        "actual_operation": plan.operation,
        "sql": plan.sql,
        "rows": actual_rows[: len(case.get("expected_rows", [])) or 3],
        "failed_checks": [
            {"name": name, "actual": actual}
            for name, ok, actual in checks
            if not ok
        ],
    }


def run_eval(cases_path: Path, data_path: Path) -> Dict[str, Any]:
    cases = load_cases(cases_path)
    df = load_data(data_path)
    results = [evaluate_case(case, df) for case in cases]
    passed = sum(1 for result in results if result["passed"])
    total = len(results)

    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "cases": str(cases_path),
        "data": str(data_path),
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "accuracy": passed / total if total else 0.0,
        "results": results,
    }


def write_result(report: Dict[str, Any], results_dir: Path) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    output_path = results_dir / f"query_eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic query accuracy eval.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--min-accuracy", type=float, default=1.0)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    report = run_eval(args.cases, args.data)
    print(
        f"query eval: {report['passed']}/{report['total']} passed "
        f"({report['accuracy']:.1%})"
    )
    for result in report["results"]:
        marker = "PASS" if result["passed"] else "FAIL"
        print(
            f"{marker} {result['id']}: tool={result['actual_tool']} "
            f"operation={result['actual_operation']}"
        )
        for failed in result["failed_checks"]:
            print(f"  failed {failed['name']}: actual={failed['actual']}")

    if not args.no_write:
        output_path = write_result(report, DEFAULT_RESULTS_DIR)
        print(f"wrote {output_path}")

    return 0 if report["accuracy"] >= args.min_accuracy else 1


if __name__ == "__main__":
    raise SystemExit(main())
