# src/agents/incident_agent.py
"""
IncidentAgent - 인시던트 조사 및 근본원인 분석 (RCA)

- MySQL을 통한 정밀 타임라인 재구성
- Chroma를 통한 의미 기반 컨텍스트 검색
- 명령어 시퀀스 / 공격 경로 후보 분석
- Structured Output + LLM 기반 고품질 조사 보고서
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from src.prompts import PROMPTS
from src.tools.chroma_retriever import chroma_retriever
from src.tools.mysql_tool import mysql_query_tool
from src.utils import json_safe, safe_json_dumps


# =============================================================================
# Pydantic Models
# =============================================================================
class TimelineEvent(BaseModel):
    timestamp: str
    user_name: str
    command: str
    exit_code: int
    client_ip: Optional[str] = None
    session_id: Optional[str] = None
    current_dir: Optional[str] = None


class RootCauseCandidate(BaseModel):
    description: str
    confidence: float  # 0.0 ~ 1.0
    supporting_evidence: List[str] = Field(default_factory=list)


class IncidentResult(BaseModel):
    """인시던트 조사 결과"""
    incident_summary: str
    timeline: List[TimelineEvent] = Field(default_factory=list)
    root_cause_candidates: List[RootCauseCandidate] = Field(default_factory=list)
    attack_paths: List[str] = Field(default_factory=list)
    evidence_summary: str
    recommendations: List[str] = Field(default_factory=list)
    analysis_window: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# =============================================================================
# 쿼리 파싱 헬퍼
# =============================================================================
USER_RE = re.compile(
    r"\b(admin|root|hacker|user[A-Za-z0-9_]+|dev\d+|appmgr\d+|dba\d+)\b",
    re.IGNORECASE,
)
DAYS_RE = re.compile(r"(\d+)\s*(?:일|days?)", re.IGNORECASE)
SESSION_RE = re.compile(
    r"\b(sess_[A-Za-z0-9_]+|hacked-[A-Za-z0-9_-]+|[a-f0-9]{8,})\b",
    re.IGNORECASE,
)

RISK_COMMAND_CONDITIONS = [
    "command LIKE '%sudo%'",
    "command LIKE '%rm -rf%'",
    "command LIKE '%chmod 777%'",
    "command LIKE '%chown %'",
    "command LIKE '%/etc/passwd%'",
    "command LIKE '%/etc/shadow%'",
    "command LIKE '%iptables%'",
    "command LIKE '%curl %'",
    "command LIKE '%wget %'",
    "command LIKE '%nc %'",
    "command LIKE '%netcat%'",
]


def _parse_incident_context(query: str) -> Dict[str, Any]:
    return {
        "user_name": (m.group(1) if (m := USER_RE.search(query)) else None),
        "days": int(m.group(1)) if (m := DAYS_RE.search(query)) else 7,
        "session_id": (m.group(1) if (m := SESSION_RE.search(query)) else None),
        "keywords": query,
    }


def _escape_sql(value: str) -> str:
    return str(value).replace("'", "''") if value else ""


def _build_timeline_sql(ctx: Dict[str, Any], limit: int = 60) -> str:
    clauses = []
    if ctx.get("user_name"):
        clauses.append(f"user_name = '{_escape_sql(ctx['user_name'])}'")
    if ctx.get("session_id"):
        clauses.append(f"session_id = '{_escape_sql(ctx['session_id'])}'")

    clauses.append(
        f"timestamp >= (SELECT MAX(timestamp) FROM command_history) - INTERVAL {ctx['days']} DAY"
    )
    if not ctx.get("user_name") and not ctx.get("session_id"):
        clauses.append(f"({_suspicious_condition_sql()})")

    where = " AND ".join(clauses)

    return f"""
SELECT timestamp, user_name, command, exit_code, client_ip, server_ip, session_id, current_dir
FROM command_history
WHERE {where}
ORDER BY timestamp ASC
LIMIT {limit}
""".strip()


# =============================================================================
# 분석 로직
# =============================================================================
def _build_timeline(rows: List[Dict[str, Any]]) -> List[TimelineEvent]:
    events: List[TimelineEvent] = []
    for r in rows:
        events.append(
            TimelineEvent(
                timestamp=str(r.get("timestamp", "")),
                user_name=str(r.get("user_name", "")),
                command=str(r.get("command", "")),
                exit_code=int(r.get("exit_code", 0) or 0),
                client_ip=r.get("client_ip"),
                session_id=r.get("session_id"),
                current_dir=r.get("current_dir"),
            )
        )
    return events


def _detect_attack_paths(timeline: List[TimelineEvent]) -> List[str]:
    """간단한 명령어 체인 탐지 (확장 가능)"""
    paths: List[str] = []
    cmd_sequence = [e.command.lower() for e in timeline]

    # wget/curl -> chmod pattern
    for i in range(len(cmd_sequence) - 1):
        if any(x in cmd_sequence[i] for x in ["wget", "curl"]) and "chmod" in cmd_sequence[i + 1]:
            paths.append(f"Download -> Permission Change: {timeline[i].command} -> {timeline[i+1].command}")

    for i, cmd in enumerate(cmd_sequence):
        if "base64" in cmd and i + 1 < len(cmd_sequence):
            paths.append(f"Obfuscation detected: {timeline[i].command}")
        if "nc " in cmd or "netcat" in cmd:
            paths.append(f"Possible listener/backdoor command: {timeline[i].command}")
        if "/etc/shadow" in cmd or "/etc/passwd" in cmd:
            paths.append(f"Sensitive account file access: {timeline[i].command}")

    return paths[:5] or ["명확한 공격 체인 패턴이 탐지되지 않았습니다."]


def _generate_root_cause_candidates(timeline: List[TimelineEvent], chroma_context: List[Dict]) -> List[RootCauseCandidate]:
    candidates: List[RootCauseCandidate] = []

    if not timeline:
        return candidates

    # 가장 많은 실패가 발생한 명령어 근처
    failed = [e for e in timeline if e.exit_code != 0]
    if failed:
        candidates.append(
            RootCauseCandidate(
                description=f"{failed[0].user_name} 사용자가 실패한 명령어 다수 실행 ({len(failed)}회)",
                confidence=0.65,
                supporting_evidence=[failed[0].command],
            )
        )

    # 외부 IP에서 접속한 세션
    external = [e for e in timeline if e.client_ip and not e.client_ip.startswith(("10.", "172.16.", "192.168."))]
    if external:
        candidates.append(
            RootCauseCandidate(
                description="외부 IP에서의 접속 후 의심스러운 활동",
                confidence=0.55,
                supporting_evidence=[f"Client IP: {external[0].client_ip}"],
            )
        )

    risky = [
        e
        for e in timeline
        if any(token in e.command.lower() for token in ["curl ", "wget ", "nc ", "/etc/shadow", "/etc/passwd", "sudo -l"])
    ]
    if risky:
        candidates.append(
            RootCauseCandidate(
                description=f"{risky[0].user_name} 사용자의 위험 명령어 실행",
                confidence=0.75,
                supporting_evidence=[risky[0].command],
            )
        )

    return candidates


def _suspicious_condition_sql() -> str:
    external_ip = (
        "client_ip NOT LIKE '10.%' AND "
        "client_ip NOT LIKE '172.16.%' AND "
        "client_ip NOT LIKE '192.168.%'"
    )
    return f"exit_code != 0 OR {_risk_condition_sql()} OR ({external_ip})"


def _risk_condition_sql() -> str:
    return " OR ".join(RISK_COMMAND_CONDITIONS)


def _incident_subject(ctx: Dict[str, Any], timeline: List[TimelineEvent]) -> str:
    if ctx.get("user_name"):
        return str(ctx["user_name"])
    if not timeline:
        return "Unknown user"

    scores: Dict[str, int] = {}
    for event in timeline:
        score = 1
        command = event.command.lower()
        if event.exit_code != 0:
            score += 2
        if any(token in command for token in ["curl ", "wget ", "nc ", "/etc/shadow", "/etc/passwd", "sudo -l"]):
            score += 4
        if event.client_ip and not event.client_ip.startswith(("10.", "172.16.", "192.168.")):
            score += 3
        scores[event.user_name] = scores.get(event.user_name, 0) + score

    return max(scores.items(), key=lambda item: item[1])[0] if scores else "Unknown user"


# =============================================================================
# IncidentAgent
# =============================================================================
INCIDENT_POLICY = """
Response language policy:
- 한국어로 명확하고 조사 보고서 스타일로 작성하세요.
- 타임라인은 시간순으로 사실만 나열하세요.
- 근본원인 분석은 증거 기반으로 보수적으로 작성하세요.
"""


class IncidentAgent:
    def __init__(
        self,
        llm: Any,
        mysql_tool: Any = None,
        chroma_tool: Any = None,
        prompts: Optional[Dict[str, str]] = None,
    ):
        self.llm = llm
        # None 전달 시 안전 fallback
        self.mysql_tool = mysql_tool or mysql_query_tool
        self.chroma_tool = chroma_tool or chroma_retriever
        self.prompts = prompts or PROMPTS

        self.prompt = ChatPromptTemplate.from_template(
            INCIDENT_POLICY
            + "\n\n"
            + self.prompts.get("incident", PROMPTS["incident"])
            + "\n\n"
            + "User Query: {query}\n\n"
            + "=== Incident Context ===\n"
            + "Summary: {incident_summary}\n\n"
            + "Timeline (first 15 events):\n{timeline_sample}\n\n"
            + "Attack Paths:\n{attack_paths}\n\n"
            + "Root Cause Candidates:\n{root_causes}\n\n"
            + "위 정보를 바탕으로 전문적인 인시던트 조사 보고서를 작성하세요."
        )

    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        query = state["user_query"]
        ctx = _parse_incident_context(query)

        # 방어 코드: 도구가 None이면 명확한 에러 발생
        if self.mysql_tool is None:
            raise RuntimeError("IncidentAgent: mysql_tool이 초기화되지 않았습니다. 서버를 재시작하세요.")
        if self.chroma_tool is None:
            raise RuntimeError("IncidentAgent: chroma_tool이 초기화되지 않았습니다. 서버를 재시작하세요.")

        # 1. MySQL 타임라인 수집
        timeline_sql = _build_timeline_sql(ctx)
        timeline_rows = self.mysql_tool.invoke({"sql_query": timeline_sql})
        timeline_data = timeline_rows.get("data", []) if timeline_rows.get("success") else []

        timeline = _build_timeline(timeline_data)

        # 2. Chroma 의미 검색 (인시던트 주변 컨텍스트)
        try:
            chroma_result = self.chroma_tool.invoke({"query": query, "top_k": 8})
        except Exception:
            chroma_result = []

        # 3. 분석 수행
        attack_paths = _detect_attack_paths(timeline)
        root_causes = _generate_root_cause_candidates(timeline, chroma_result)

        subject = _incident_subject(ctx, timeline)
        incident_summary = (
            f"{subject} 관련 의심 인시던트 "
            f"(최근 {ctx['days']}일, 세션: {ctx.get('session_id') or 'N/A'})"
        )

        result = IncidentResult(
            incident_summary=incident_summary,
            timeline=timeline,
            root_cause_candidates=root_causes,
            attack_paths=attack_paths,
            evidence_summary=f"MySQL {len(timeline)}건 + Chroma {len(chroma_result)}건 분석 완료",
            recommendations=[
                "의심 세션에 대한 추가 포렌식 조사 수행",
                "해당 사용자 계정 비밀번호 및 SSH 키 교체 검토",
                "관련 IP에 대한 방화벽/IDS 룰 추가",
            ],
            analysis_window={"days": ctx["days"], "user": subject, "session": ctx.get("session_id")},
        )

        # Use a deterministic evidence-based report so the incident conclusion
        # cannot contradict the structured timeline and root-cause candidates.
        final_report = _format_incident_for_user(result)

        # State 저장
        payload = result.model_dump() if hasattr(result, "model_dump") else result.dict()

        state.setdefault("tool_results", {})["incident"] = {
            "params": ctx,
            "timeline_count": len(timeline),
            "chroma_hits": len(chroma_result) if isinstance(chroma_result, list) else 0,
            "structured_result": payload,
        }

        state["incident_result"] = payload
        state["structured_response"] = {"incident": payload}
        state["final_response"] = final_report

        state.setdefault("messages", []).append(AIMessage(content=final_report))

        return state


def _format_incident_for_user(result: IncidentResult) -> str:
    lines: List[str] = [
        "## 인시던트 조사 결과",
        "",
        f"**요약:** {result.incident_summary}",
        f"**증거 요약:** {result.evidence_summary}",
        "",
    ]

    if result.timeline:
        lines.append("### 주요 타임라인")
        for event in result.timeline[:12]:
            lines.append(
                f"- `{event.timestamp}` `{event.user_name}` @ `{event.client_ip or 'N/A'}` "
                f"`{event.command}` (exit `{event.exit_code}`, session `{event.session_id or 'N/A'}`)"
            )
        lines.append("")
    else:
        lines.extend(
            [
                "### 주요 타임라인",
                "- 조건에 맞는 의심 로그가 없습니다.",
                "",
            ]
        )

    if result.root_cause_candidates:
        lines.append("### 근본 원인 후보")
        for candidate in result.root_cause_candidates:
            evidence = ", ".join(f"`{item}`" for item in candidate.supporting_evidence[:3])
            lines.append(
                f"- {candidate.description} "
                f"(신뢰도 `{candidate.confidence:.2f}`"
                f"{', 증거 ' + evidence if evidence else ''})"
            )
        lines.append("")

    if result.attack_paths:
        lines.append("### 공격 경로 단서")
        for path in result.attack_paths:
            lines.append(f"- {path}")
        lines.append("")

    if result.recommendations:
        lines.append("### 권고사항")
        for index, recommendation in enumerate(result.recommendations, 1):
            lines.append(f"{index}. {recommendation}")

    return "\n".join(lines).strip()

