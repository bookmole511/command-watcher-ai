import json
import unittest
from pathlib import Path

from src.agents.router import RouterAgent
from src.utils import AgentIntent


CASES_PATH = Path(__file__).resolve().parents[1] / "harness" / "router_cases.json"


class StubChain:
    def __init__(self, intent: str):
        self.intent = intent
        self.payloads = []

    def invoke(self, payload):
        self.payloads.append(payload)
        return AgentIntent(intent=self.intent, reasoning=f"fixture intent: {self.intent}")


class FailingChain:
    def invoke(self, payload):
        raise RuntimeError("synthetic router failure")


class RouterContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))

    def test_router_updates_state_for_fixture_cases(self):
        for case in self.cases:
            with self.subTest(case=case["id"]):
                chain = StubChain(case["expected_intent"])
                router = RouterAgent(llm=None, chain=chain)
                state = {
                    "user_query": case["query"],
                    "messages": [],
                }

                result = router(state)

                self.assertIs(result, state)
                self.assertEqual(result["intent"], case["expected_intent"])
                self.assertEqual(result["selected_agent"], f"{case['expected_intent']}_agent")
                self.assertTrue(result["reasoning"])
                self.assertEqual(len(result["messages"]), 1)
                self.assertEqual(chain.payloads[0]["query"], case["query"])
                self.assertIn("format_instructions", chain.payloads[0])

    def test_router_allows_missing_messages_list(self):
        chain = StubChain("query")
        router = RouterAgent(llm=None, chain=chain)

        result = router({"user_query": "최근 로그를 조회해줘"})

        self.assertEqual(result["intent"], "query")
        self.assertEqual(len(result["messages"]), 1)

    def test_router_falls_back_to_general_on_chain_error(self):
        router = RouterAgent(llm=None, chain=FailingChain())

        result = router({"user_query": "무엇이든 실패시키기", "messages": []})

        self.assertEqual(result["intent"], "general")
        self.assertEqual(result["selected_agent"], "general_agent")
        self.assertIn("Router", result["error"])


if __name__ == "__main__":
    unittest.main()
