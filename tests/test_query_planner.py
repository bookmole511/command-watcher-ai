import json
import unittest
from pathlib import Path

from src.agents.query_planner import CHROMA_STATS_TOOL, MYSQL_TOOL, choose_query_plan


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

    def test_user_count_uses_mysql_for_source_of_truth(self):
        plan = choose_query_plan("전체 사용자 수 알려줘")

        self.assertEqual(plan.tool, MYSQL_TOOL)
        self.assertEqual(plan.operation, "user_count")
        self.assertIn("COUNT(DISTINCT user_name)", plan.sql)

    def test_chroma_user_count_uses_metadata_stats(self):
        plan = choose_query_plan("chroma_db에는 몇 명의 사용자가 있어?")

        self.assertEqual(plan.tool, CHROMA_STATS_TOOL)
        self.assertEqual(plan.operation, "chroma_user_count")
        self.assertTrue(plan.params["include_users"])

    def test_user_list_uses_grouped_mysql_query(self):
        plan = choose_query_plan("사용자 목록 알려줘")

        self.assertEqual(plan.tool, MYSQL_TOOL)
        self.assertEqual(plan.operation, "user_list")
        self.assertIn("GROUP BY user_name", plan.sql)


if __name__ == "__main__":
    unittest.main()
