import json
import unittest
from pathlib import Path

from src.agents.query_planner import choose_query_plan


CASES_PATH = Path(__file__).resolve().parents[1] / "harness" / "query_cases.json"


class QueryPlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))

    def test_fixture_tool_and_operation_selection(self):
        for case in self.cases:
            with self.subTest(case=case["id"]):
                plan = choose_query_plan(case["query"])

                self.assertEqual(plan.tool, case["expected_tool"])
                self.assertEqual(plan.operation, case["expected_operation"])

    def test_mysql_cases_have_sql(self):
        for case in self.cases:
            if case["expected_tool"] != "mysql":
                continue

            with self.subTest(case=case["id"]):
                plan = choose_query_plan(case["query"])

                self.assertTrue(plan.sql)
                for expected in case.get("expected_sql_contains", []):
                    self.assertIn(expected, plan.sql)


if __name__ == "__main__":
    unittest.main()
