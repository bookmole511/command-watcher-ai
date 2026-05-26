# src/agents/recommendation_agent.py
"""
RecommendationAgent - 사용자 명령어 패턴 기반 워크플로우 최적화 추천

AnomalyAgent 스타일의 풍부한 데이터 수집 + LLM 합성 구조를 따릅니다.
- 쿼리에서 대상 사용자/기간/포커스 자동 추출
- 개인화된 다중 MySQL 분석 (성공률, 최근 시퀀스, 실패 패턴)
- 구조화된 tool_results 저장 + 자연어 최종 응답
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
from src.utils import safe_json_dumps, json_safe


# =============================================================================
# Structured Output Model (AnomalyAgent 패턴 준용)
# =============================================================================
class RecommendationResult(BaseModel):
    """추천 결과의 구조화된 표현 (디버깅/추후 API 확장용)"""
    target_user: Optional[str] = Field(None, description="추천 대상 사용자 (없으면 전체 분석)")
    days: int = Field(30, description="분석 대상 기간(일)")
    focus_areas: List[str] = Field(default_factory=list, description="쿼리에서 감지된 관심 영역 (docker, python 등)")
    user_top_commands: List[Dict[str, Any]] = Field(default_factory=list)
    user_recent_sequence: List[Dict[str, Any]] = Field(default_factory=list, description="사용자의 실제 최근 명령 시퀀스 샘플")
    global_top_reliable: List[Dict[str, Any]] = Field(default_factory=list, description="전체적으로 성공률 높은 인기 명령어")
    failure_patterns: List[Dict[str, Any]] = Field(default_factory=list)
    summary_stats: Dict[str, Any] = Field(default_factory=dict)
    data_quality: str = "ok"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# =============================================================================
# 쿼리 파싱 헬퍼 (query_planner / anomaly_agent 패턴 재사용)
# =============================================================================
USER_RE = re.compile(r"\b(admin|root|user[A-Za-z0-9_]+)\b", re.IGNORECASE)
DAYS_RE = re.compile(r"(\d+)\s*(?:일|days?)", re.IGNORECASE)

FOCUS_KEYWORDS = {
    "docker": ["docker", "컨테이너", "compose"],
    "python": ["python", "pip", "venv", "가상환경", "torch", "inference", "train"],
    "sudo": ["sudo", "권한", "root"],
    "file": ["rm -rf", "mv", "cp", "rsync", "tar"],
    "log": ["log", "로그", "cat /var", "tail"],
    "system": ["df -h", "free -h", "top", "htop", "ps aux", "disk", "메모리"],
}


def _detect_target_user(query: str) -> Optional[str]:
    match = USER_RE.search(query)
    return match.group(1) if match else None


def _detect_days(query: str) -> int:
    match = DAYS_RE.search(query)
    if match:
        return max(1, min(int(match.group(1)), 365))
    return 30


def _detect_focus_areas(query: str) -> List[str]:
    normalized = query.lower()
    areas: List[str] = []
    for area, keywords in FOCUS_KEYWORDS.items():
        if any(kw.lower() in normalized for kw in keywords):
            areas.append(area)
    return areas or ["general"]


def _escape_sql(value: str) -> str:
    """간단한 SQL 인젝션 방지 (AnomalyAgent와 동일 패턴)"""
    if value is None:
        return ""
    return str(value).replace("'", "''")


# =============================================================================
# SQL 생성기 (개인화 + 성공률 + 시퀀스 중심)
# =============================================================================
def _user_stats_sql(user_name: str, days: int) -> str:
    safe_user = _escape_sql(user_name)
    return f"""
SELECT 
    command,
    COUNT(*) AS use_count,
    SUM(CASE WHEN exit_code = 0 THEN 1 ELSE 0 END) AS success_count,
    ROUND(SUM(CASE WHEN exit_code = 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS success_rate,
    MAX(timestamp) AS last_used,
    COUNT(DISTINCT session_id) AS session_count
FROM command_history
WHERE user_name = '{safe_user}'
  AND timestamp >= (SELECT MAX(timestamp) FROM command_history) - INTERVAL {max(1, days)} DAY
GROUP BY command
ORDER BY use_count DESC, success_rate DESC
LIMIT 15
""".strip()


def _user_recent_sequence_sql(user_name: str, days: int, limit: int = 40) -> str:
    safe_user = _escape_sql(user_name)
    return f"""
SELECT 
    command, timestamp, exit_code, current_dir, session_id
FROM command_history
WHERE user_name = '{safe_user}'
  AND timestamp >= (SELECT MAX(timestamp) FROM command_history) - INTERVAL {max(1, days)} DAY
ORDER BY timestamp DESC
LIMIT {limit}
""".strip()


def _user_failures_sql(user_name: str, days: int) -> str:
    safe_user = _escape_sql(user_name)
    return f"""
SELECT 
    command,
    COUNT(*) AS failure_count,
    MAX(timestamp) AS last_failed
FROM command_history
WHERE user_name = '{safe_user}'
  AND exit_code != 0
  AND timestamp >= (SELECT MAX(timestamp) FROM command_history) - INTERVAL {max(1, days)} DAY
GROUP BY command
ORDER BY failure_count DESC
LIMIT 10
""".strip()


def _global_top_reliable_sql(days: int, limit: int = 12) -> str:
    """성공률 70% 이상 + 사용량 일정 이상인 신뢰성 높은 명령어 (전역)"""
    return f"""
SELECT 
    command,
    COUNT(*) AS total_uses,
    ROUND(SUM(CASE WHEN exit_code = 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS success_rate,
    COUNT(DISTINCT user_name) AS user_count
FROM command_history
WHERE exit_code = 0
  AND timestamp >= (SELECT MAX(timestamp) FROM command_history) - INTERVAL {max(1, days)} DAY
GROUP BY command
HAVING total_uses >= 2 AND success_rate >= 70
ORDER BY total_uses DESC, success_rate DESC
LIMIT {limit}
""".strip()


def _rows(result: Dict[str, Any], limit: int = 50) -> List[Dict[str, Any]]:
    """AnomalyAgent의 _rows 헬퍼 패턴"""
    if not result or result.get("success") is False:
        return []
    data = result.get("data")
    if not isinstance(data, list):
        return []
    return [dict(r) for r in data[:limit] if isinstance(r, dict)]


# =============================================================================
# RecommendationAgent 본체
# =============================================================================
RECOMMENDATION_POLICY = """
Response language & quality policy:
- Answer only in Korean (or English if user query is clearly English).
- Preserve exact command strings, usernames, paths, and numbers as-is.
- Always output in clean Markdown format (use headings, lists, and `code` blocks).
- Be concrete: always include 2~4 specific before/after command examples using code formatting.
- When data is sparse, explicitly say "현재 이력이 부족하여 일반적인 조언을 드립니다".
- Never hallucinate commands that do not appear in the provided tool results.
- Use `inline code` for commands and triple backticks for multi-line examples when helpful.
"""


class RecommendationAgent:
    def __init__(
        self,
        llm: Any,
        mysql_tool: Any = None,
    ):
        self.llm = llm
        self.mysql_tool = mysql_tool or mysql_query_tool

        self.prompt = ChatPromptTemplate.from_template(
            RECOMMENDATION_POLICY
            + "\n\n"
            + PROMPTS["recommendation"]
            + "\n\n"
            + "User query: {query}\n\n"
            + "=== 분석 대상 ===\n"
            + "target_user: {target_user}\n"
            + "analysis_days: {days}\n"
            + "focus_areas: {focus_areas}\n\n"
            + "=== 사용자 개인 통계 (성공률 포함) ===\n{user_stats}\n\n"
            + "=== 사용자의 실제 최근 명령 시퀀스 (워크플로우 파악용) ===\n{recent_sequence}\n\n"
            + "=== 전체적으로 신뢰성 높은 명령어 패턴 ===\n{global_reliable}\n\n"
            + "=== 사용자의 실패 패턴 ===\n{failures}\n\n"
            + "위 데이터를 바탕으로 실용적이고 구체적인 추천을 작성하세요."
        )

    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        query = state["user_query"]

        # 1. 쿼리 의도 파싱
        target_user = _detect_target_user(query)
        days = _detect_days(query)
        focus_areas = _detect_focus_areas(query)

        params = {
            "target_user": target_user,
            "days": days,
            "focus_areas": focus_areas,
            "query": query,
        }

        # 2. 데이터 수집 (개인화 우선)
        user_stats: List[Dict[str, Any]] = []
        recent_sequence: List[Dict[str, Any]] = []
        failures: List[Dict[str, Any]] = []
        global_reliable: List[Dict[str, Any]] = []

        try:
            if target_user:
                # 사용자 중심 분석
                user_stats = _rows(
                    self.mysql_tool.invoke({"sql_query": _user_stats_sql(target_user, days)})
                )
                recent_sequence = _rows(
                    self.mysql_tool.invoke({"sql_query": _user_recent_sequence_sql(target_user, days)})
                )
                failures = _rows(
                    self.mysql_tool.invoke({"sql_query": _user_failures_sql(target_user, days)})
                )

            # 공통: 전체 신뢰성 높은 패턴 (항상 수집)
            global_reliable = _rows(
                self.mysql_tool.invoke({"sql_query": _global_top_reliable_sql(days)})
            )

            # 최근 시퀀스가 없으면 전체에서 샘플 (fallback)
            if not recent_sequence and not target_user:
                # global 최근 활동 일부 (전체 추천용)
                recent_sequence = _rows(
                    self.mysql_tool.invoke(
                        {
                            "sql_query": (
                                "SELECT command, timestamp, exit_code, user_name, session_id "
                                "FROM command_history ORDER BY timestamp DESC LIMIT 25"
                            )
                        }
                    )
                )

        except Exception as e:
            # 데이터 수집 실패 시 graceful 처리
            state.setdefault("error", f"Recommendation data collection failed: {e}")

        # 3. Structured payload 구성
        structured = RecommendationResult(
            target_user=target_user,
            days=days,
            focus_areas=focus_areas,
            user_top_commands=user_stats,
            user_recent_sequence=recent_sequence[:25],  # 과도한 길이 제한
            global_top_reliable=global_reliable,
            failure_patterns=failures,
            summary_stats={
                "user_command_types": len(user_stats),
                "has_personal_data": bool(target_user and user_stats),
                "recent_commands_count": len(recent_sequence),
            },
            data_quality="ok" if (user_stats or global_reliable) else "sparse",
        )

        # 4. State에 상세 tool 결과 저장 (디버깅/평가용)
        state.setdefault("tool_results", {})["recommendation"] = {
            "params": params,
            "structured": structured.model_dump() if hasattr(structured, "model_dump") else structured.dict(),
            "raw": {
                "user_stats": json_safe(user_stats),
                "recent_sequence_sample": json_safe(recent_sequence[:10]),
                "global_reliable": json_safe(global_reliable[:8]),
                "failures": json_safe(failures),
            },
        }

        # 5. LLM 호출로 자연어 추천 생성
        try:
            chain = self.prompt | self.llm
            response = chain.invoke(
                {
                    "query": query,
                    "target_user": target_user or "전체 사용자",
                    "days": days,
                    "focus_areas": ", ".join(focus_areas),
                    "user_stats": safe_json_dumps(user_stats) if user_stats else "데이터 없음",
                    "recent_sequence": safe_json_dumps(recent_sequence[:15]) if recent_sequence else "데이터 없음",
                    "global_reliable": safe_json_dumps(global_reliable) if global_reliable else "데이터 없음",
                    "failures": safe_json_dumps(failures) if failures else "없음",
                }
            )
            final_text = response.content
        except Exception as e:
            final_text = f"추천 생성 중 오류가 발생했습니다: {str(e)}"
            state["error"] = f"Recommendation LLM error: {e}"

        # 6. State 업데이트 (QueryAgent/AnomalyAgent와 동일한 안전 패턴)
        state["final_response"] = final_text
        state.setdefault("messages", []).append(AIMessage(content=final_text))

        # (선택) 구조화된 결과도 함께 노출 — AnomalyAgent 호환성
        state.setdefault("structured_response", {})["recommendation"] = structured.model_dump() if hasattr(structured, "model_dump") else structured.dict()

        return state
