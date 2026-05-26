# src/agents/compliance_agent.py
"""
ComplianceAgent - 컴플라이언스 감사 및 위반 리포트 생성

AnomalyAgent와 동일한 철학으로 구현:
- 결정론적 데이터 수집 + Python 기반 규칙 엔진
- Pydantic Structured Output
- 풍부한 MySQL 분석 쿼리
- LLM은 최종 자연어 리포트 생성에만 사용
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from src.prompts import PROMPTS
from src.tools.mysql_tool import mysql_query_tool
from src.utils import json_safe, safe_json_dumps


# =============================================================================
# Compliance Rules (내부 규칙 엔진)
# =============================================================================
COMPLIANCE_RULES: List[Dict[str, Any]] = [
    {
        "rule_id": "CR-001",
        "name": "Privileged Command Execution",
        "pattern": r"^\s*sudo\s+",
        "severity": "High",
        "category": "Privilege Escalation",
        "description": "sudo를 통한 특권 명령 실행 (최소 권한 원칙 위반 가능성)",
    },
    {
        "rule_id": "CR-002",
        "name": "Destructive File Operation",
        "pattern": r"rm\s+-rf|rm\s+-r\s+/",
        "severity": "Critical",
        "category": "Data Destruction",
        "description": "재귀적 삭제 명령 (데이터 유실 위험)",
    },
    {
        "rule_id": "CR-003",
        "name": "Remote Code Download & Execute",
        "pattern": r"(curl|wget)\s+.*\|\s*(bash|sh|python)",
        "severity": "Critical",
        "category": "Remote Code Execution",
        "description": "원격에서 코드를 다운로드하여 즉시 실행",
    },
    {
        "rule_id": "CR-004",
        "name": "Base64 / Obfuscated Command",
        "pattern": r"base64\s+-d|echo\s+.*\|\s*base64",
        "severity": "High",
        "category": "Obfuscation",
        "description": "명령어 난독화 시도 (base64 디코딩)",
    },
    {
        "rule_id": "CR-005",
        "name": "Network Tool with High Risk",
        "pattern": r"\b(nc|netcat|ncat)\s+.*(-e|-c)",
        "severity": "High",
        "category": "Lateral Movement",
        "description": "역방향 쉘 또는 바인드 쉘 생성 가능성",
    },
    {
        "rule_id": "CR-006",
        "name": "Excessive Failed Commands",
        "pattern": None,  # 동적 규칙 (exit_code != 0)
        "severity": "Medium",
        "category": "Operational Failure",
        "description": "비정상적으로 많은 실패 명령어",
    },
]


class ComplianceViolation(BaseModel):
    rule_id: str
    rule_name: str
    severity: str
    category: str
    command: str
    user_name: str
    timestamp: str
    count: int = 1
    details: Optional[str] = None


class ComplianceResult(BaseModel):
    """컴플라이언스 감사 전체 결과"""
    compliance_score: float = Field(..., ge=0, le=100, description="0~100점 (높을수록 준수)")
    total_violations: int
    severity_breakdown: Dict[str, int] = Field(default_factory=dict)
    violations: List[ComplianceViolation] = Field(default_factory=list)
    top_violating_users: List[Dict[str, Any]] = Field(default_factory=list)
    summary: str
    recommendations: List[str] = Field(default_factory=list)
    report_markdown: str = ""
    analysis_period_days: int = 30
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# =============================================================================
# SQL 생성기
# =============================================================================
def _escape_sql(value: str) -> str:
    return str(value).replace("'", "''") if value else ""


def _where_days(days: int) -> str:
    return (
        f"timestamp >= (SELECT MAX(timestamp) FROM command_history) "
        f"- INTERVAL {max(1, int(days))} DAY"
    )


def _high_risk_commands_sql(days: int, limit: int = 100) -> str:
    patterns = [
        r"sudo\s+",
        r"rm\s+-rf",
        r"curl\s+.*\|\s*(bash|sh)",
        r"wget\s+.*\|\s*(bash|sh)",
        r"base64\s+-d",
        r"\bnc\s+.*-e",
    ]
    like_clauses = " OR ".join([f"command REGEXP '{p}'" for p in patterns])
    return f"""
SELECT user_name, command, timestamp, exit_code, session_id
FROM command_history
WHERE ({like_clauses})
  AND {_where_days(days)}
ORDER BY timestamp DESC
LIMIT {limit}
""".strip()


def _failed_commands_sql(days: int, limit: int = 80) -> str:
    return f"""
SELECT user_name, command, timestamp, exit_code, session_id
FROM command_history
WHERE exit_code != 0
  AND {_where_days(days)}
ORDER BY timestamp DESC
LIMIT {limit}
""".strip()


def _user_violation_stats_sql(days: int) -> str:
    return f"""
SELECT 
    user_name,
    COUNT(*) as total_commands,
    SUM(CASE WHEN exit_code != 0 THEN 1 ELSE 0 END) as failure_count,
    COUNT(DISTINCT command) as unique_commands
FROM command_history
WHERE {_where_days(days)}
GROUP BY user_name
ORDER BY failure_count DESC, total_commands DESC
LIMIT 15
""".strip()


def _rows(result: Dict[str, Any], limit: int = 200) -> List[Dict[str, Any]]:
    if not result or result.get("success") is False:
        return []
    data = result.get("data")
    if not isinstance(data, list):
        return []
    return [dict(r) for r in data[:limit] if isinstance(r, dict)]


# =============================================================================
# 규칙 매칭 및 결과 빌드
# =============================================================================
def _match_rules(rows: List[Dict[str, Any]]) -> List[ComplianceViolation]:
    violations: List[ComplianceViolation] = []

    for row in rows:
        command = str(row.get("command", ""))
        user = str(row.get("user_name", "unknown"))
        ts = str(row.get("timestamp", ""))

        for rule in COMPLIANCE_RULES:
            if rule["pattern"] and re.search(rule["pattern"], command, re.IGNORECASE):
                violations.append(
                    ComplianceViolation(
                        rule_id=rule["rule_id"],
                        rule_name=rule["name"],
                        severity=rule["severity"],
                        category=rule["category"],
                        command=command,
                        user_name=user,
                        timestamp=ts,
                    )
                )
                break  # 한 명령어는 가장 먼저 매칭된 규칙 하나만

    return violations


def _build_compliance_result(
    high_risk_rows: List[Dict],
    failed_rows: List[Dict],
    user_stats: List[Dict],
    days: int,
) -> ComplianceResult:
    # 규칙 기반 위반 탐지
    rule_violations = _match_rules(high_risk_rows)

    # 실패 명령어 중 과도한 실패를 별도 Medium 위반으로 처리
    failure_by_user: Dict[str, int] = {}
    for r in failed_rows:
        u = r.get("user_name", "unknown")
        failure_by_user[u] = failure_by_user.get(u, 0) + 1

    for user, count in failure_by_user.items():
        if count >= 15:  # 임계값 (실제 환경에서는 설정 가능하게)
            rule_violations.append(
                ComplianceViolation(
                    rule_id="CR-006",
                    rule_name="Excessive Failed Commands",
                    severity="Medium",
                    category="Operational Failure",
                    command=f"<{count} failed commands>",
                    user_name=user,
                    timestamp="",
                    count=count,
                    details=f"최근 {days}일 동안 {count}회 실패",
                )
            )

    # 심각도별 집계
    severity_breakdown: Dict[str, int] = {}
    for v in rule_violations:
        severity_breakdown[v.severity] = severity_breakdown.get(v.severity, 0) + 1

    # 사용자별 위반 집계
    user_violation_count: Dict[str, int] = {}
    for v in rule_violations:
        user_violation_count[v.user_name] = user_violation_count.get(v.user_name, 0) + v.count

    top_users = sorted(
        [{"user_name": u, "violation_count": c} for u, c in user_violation_count.items()],
        key=lambda x: x["violation_count"],
        reverse=True,
    )[:5]

    # 컴플라이언스 점수 계산 (간단한 휴리스틱)
    critical = severity_breakdown.get("Critical", 0)
    high = severity_breakdown.get("High", 0)
    medium = severity_breakdown.get("Medium", 0)

    penalty = critical * 12 + high * 6 + medium * 2.5
    score = max(0.0, min(100.0, round(100 - penalty, 1)))

    # 요약 문장
    total = len(rule_violations)
    summary = (
        f"총 {total}건의 컴플라이언스 위반이 탐지되었습니다. "
        f"Critical {critical}건, High {high}건, Medium {medium}건."
        if total > 0
        else "분석 기간 내 주요 컴플라이언스 위반이 탐지되지 않았습니다."
    )

    # 기본 권고사항 (LLM이 더 다듬음)
    recommendations: List[str] = []
    if critical > 0:
        recommendations.append("Critical 위반 명령어 사용을 즉시 금지하고, 해당 사용자 접근 권한을 검토하세요.")
    if high > 0:
        recommendations.append("sudo 사용을 최소화하고, sudoers 설정을 Principle of Least Privilege에 맞게 재구성하세요.")
    if total > 10:
        recommendations.append("명령어 감사 로깅을 강화하고, 주기적인 컴플라이언스 리뷰 프로세스를 도입하세요.")

    return ComplianceResult(
        compliance_score=score,
        total_violations=total,
        severity_breakdown=severity_breakdown,
        violations=rule_violations[:50],  # 과도한 크기 제한
        top_violating_users=top_users,
        summary=summary,
        recommendations=recommendations,
        analysis_period_days=days,
    )


# =============================================================================
# ComplianceAgent
# =============================================================================
COMPLIANCE_POLICY = """
Response language policy:
- 한국어로 명확하고 감사 보고서 스타일로 작성하세요.
- 사실 기반으로 작성하고, 과도한 추측은 피하세요.
- Markdown 형식을 적극 활용하세요 (제목, 목록, 코드 블록).
"""


class ComplianceAgent:
    def __init__(
        self,
        llm: Any,
        mysql_tool: Any = None,
        prompts: Optional[Dict[str, str]] = None,
    ):
        self.llm = llm
        # None이 명시적으로 전달되더라도 기본 도구로 fallback (workflow에서 tools.get()이 None을 줄 때 대비)
        self.mysql_tool = mysql_tool or mysql_query_tool
        self.prompts = prompts or PROMPTS

        self.prompt = ChatPromptTemplate.from_template(
            COMPLIANCE_POLICY
            + "\n\n"
            + self.prompts.get("compliance", PROMPTS["compliance"])
            + "\n\n"
            + "User Query: {query}\n\n"
            + "=== Compliance Analysis Result ===\n"
            + "compliance_score: {compliance_score}\n"
            + "total_violations: {total_violations}\n"
            + "severity_breakdown: {severity_breakdown}\n\n"
            + "Top Violating Users:\n{top_users}\n\n"
            + "Violations (sample):\n{violations_sample}\n\n"
            + "위 데이터를 바탕으로 전문적인 감사 리포트를 Markdown 형식으로 작성하세요."
        )

    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        query = state["user_query"]
        days = _detect_days(query) or 30

        # 방어 코드: 도구가 None이면 명확한 에러 발생
        if self.mysql_tool is None:
            raise RuntimeError("ComplianceAgent: mysql_tool이 초기화되지 않았습니다. 서버를 재시작하세요.")

        # 데이터 수집
        high_risk = _rows(self.mysql_tool.invoke({"sql_query": _high_risk_commands_sql(days)}))
        failed = _rows(self.mysql_tool.invoke({"sql_query": _failed_commands_sql(days)}))
        user_stats = _rows(self.mysql_tool.invoke({"sql_query": _user_violation_stats_sql(days)}))

        # Structured 결과 생성
        result = _build_compliance_result(high_risk, failed, user_stats, days)

        # LLM으로 고품질 Markdown 리포트 생성
        try:
            chain = self.prompt | self.llm
            llm_response = chain.invoke(
                {
                    "query": query,
                    "compliance_score": result.compliance_score,
                    "total_violations": result.total_violations,
                    "severity_breakdown": result.severity_breakdown,
                    "top_users": safe_json_dumps(result.top_violating_users),
                    "violations_sample": safe_json_dumps(result.violations[:15]),
                }
            )
            result.report_markdown = llm_response.content
        except Exception as e:
            result.report_markdown = f"리포트 생성 중 오류 발생: {str(e)}"

        # State 저장 (AnomalyAgent 스타일)
        payload = result.model_dump() if hasattr(result, "model_dump") else result.dict()

        state.setdefault("tool_results", {})["compliance"] = {
            "params": {"days": days, "query": query},
            "raw_high_risk": json_safe(high_risk[:30]),
            "raw_failed": json_safe(failed[:30]),
            "user_stats": json_safe(user_stats),
            "structured_result": payload,
        }

        state["compliance_result"] = payload
        state["structured_response"] = {"compliance": payload}
        state["final_response"] = result.report_markdown or result.summary

        state.setdefault("messages", []).append(AIMessage(content=state["final_response"]))

        return state


def _detect_days(query: str) -> Optional[int]:
    match = re.search(r"(\d+)\s*(?:일|days?)", query, re.IGNORECASE)
    return int(match.group(1)) if match else None

