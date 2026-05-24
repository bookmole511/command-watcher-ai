"""Run router intent evaluation against fixture cases.

This harness uses the configured Ollama model, so it is intentionally separate
from the fast offline unit tests.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agents.router import RouterAgent
from src.graph.state import create_initial_state
from src.llm import create_chat_ollama


DEFAULT_CASES = ROOT / "harness" / "router_cases.json"
DEFAULT_RESULTS_DIR = ROOT / "harness" / "results"


def load_cases(path: Path) -> List[Dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_eval(cases: List[Dict[str, Any]], limit: int | None = None) -> Dict[str, Any]:
    llm = create_chat_ollama(num_predict=256)
    router = RouterAgent(llm)
    selected_cases = cases[:limit] if limit else cases
    results = []

    for case in selected_cases:
        started = time.time()
        state = create_initial_state(case["query"])
        output = router(state)
        elapsed = round(time.time() - started, 3)
        actual = output.get("intent")
        expected = case["expected_intent"]

        results.append(
            {
                "id": case["id"],
                "query": case["query"],
                "expected_intent": expected,
                "actual_intent": actual,
                "passed": actual == expected,
                "reasoning": output.get("reasoning", ""),
                "error": output.get("error"),
                "elapsed_seconds": elapsed,
            }
        )

    passed = sum(1 for item in results if item["passed"])
    total = len(results)
    accuracy = passed / total if total else 0.0

    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "accuracy": accuracy,
        "results": results,
    }


def write_result(report: Dict[str, Any], results_dir: Path) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    output_path = results_dir / f"router_eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run live router intent evaluation.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--min-accuracy", type=float, default=0.8)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    report = run_eval(load_cases(args.cases), limit=args.limit)

    print(
        f"router eval: {report['passed']}/{report['total']} passed "
        f"({report['accuracy']:.1%})"
    )
    for item in report["results"]:
        marker = "PASS" if item["passed"] else "FAIL"
        print(
            f"{marker} {item['id']}: expected={item['expected_intent']} "
            f"actual={item['actual_intent']} elapsed={item['elapsed_seconds']}s"
        )

    if not args.no_write:
        output_path = write_result(report, DEFAULT_RESULTS_DIR)
        print(f"wrote {output_path}")

    return 0 if report["accuracy"] >= args.min_accuracy else 1


if __name__ == "__main__":
    raise SystemExit(main())
