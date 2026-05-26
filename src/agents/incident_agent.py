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
USER_RE = re.compile(r"\b(admin|root|user[A-Za-z0-9_]+)\b", re.IGNORECASE)
DAYS_RE = re.compile(r"(\d+)\s*(?:일|days?)", re.IGNORECASE)
SESSION_RE = re.compile(r"(sess_[A-Za-z0-9_]+)", re.IGNORECASE)


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

    where = " AND ".join(clauses) if clauses else "1=1"
    where += f" AND timestamp >= (SELECT MAX(timestamp) FROM command_history) - INTERVAL {ctx['days']} DAY"

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

    # wget/curl → chmod → 실행 패턴
    for i in range(len(cmd_sequence) - 2):
        if any(x in cmd_sequence[i] for x in ["wget", "curl"]) and "chmod" in cmd_sequence[i + 1]:
            paths.append(f"Download → Permission Change: {timeline[i].command} → {timeline[i+1].command}")

    # base64 디코딩 후 실행
    for i, cmd in enumerate(cmd_sequence):
        if "base64" in cmd and i + 1 < len(cmd_sequence):
            paths.append(f"Obfuscation detected: {timeline[i].command}")

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

    return candidates


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

        incident_summary = (
            f"{ctx.get('user_name') or 'Unknown user'} 관련 인시던트 "
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
            analysis_window={"days": ctx["days"], "user": ctx.get("user_name"), "session": ctx.get("session_id")},
        )

        # 4. LLM으로 고품질 조사 보고서 생성
        try:
            chain = self.prompt | self.llm
            llm_resp = chain.invoke(
                {
                    "query": query,
                    "incident_summary": result.incident_summary,
                    "timeline_sample": safe_json_dumps([e.model_dump() for e in timeline[:15]]),
                    "attack_paths": safe_json_dumps(attack_paths),
                    "root_causes": safe_json_dumps([r.model_dump() for r in root_causes]),
                }
            )
            final_report = llm_resp.content
        except Exception as e:
            final_report = f"조사 보고서 생성 중 오류: {str(e)}\n\n기본 요약:\n{result.incident_summary}"

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

