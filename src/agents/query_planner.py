"""Deterministic query planning for QueryAgent.

The planner keeps simple aggregate/log lookup questions on MySQL and leaves
semantic similarity questions to Chroma.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional


MYSQL_TOOL = "mysql"
CHROMA_TOOL = "chroma"
CHROMA_STATS_TOOL = "chroma_stats"


@dataclass(frozen=True)
class QueryPlan:
    tool: str
    reason: str
    operation: str
    sql: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)


USER_RE = re.compile(r"(admin|user[A-Za-z0-9_]+)", re.IGNORECASE)
DAYS_RE = re.compile(r"(\d+)\s*일")

COMMAND_HINTS = [
    "sudo",
    "rm -rf",
    "pip install torch",
    "docker ps",
    "cat /var/log/auth.log",
    "ps aux | grep python",
    "python train.py",
    "python inference.py",
    "cp model.pth /backup/",
    "ls -la",
    "free -h",
    "df -h",
    "htop",
    "top",
]


def choose_query_plan(query: str) -> QueryPlan:
    normalized = query.lower()

    if _looks_like_user_count(normalized):
        if _mentions_chroma(normalized):
            return QueryPlan(
                tool=CHROMA_STATS_TOOL,
                reason="Chroma DB user count needs metadata aggregation, not similarity search",
                operation="chroma_user_count",
                params={"include_users": True},
            )
        return _user_count_plan(query)

    if _is_semantic_search(normalized):
        return QueryPlan(
            tool=CHROMA_TOOL,
            reason="semantic/contextual log search is better handled by vector retrieval",
            operation="semantic_search",
            params={"top_k": 8},
        )

    if "실패" in normalized or "exit_code" in normalized or "exit code" in normalized:
        return _failed_count_by_user_plan(query)

    if any(token in normalized for token in ["ip", "아이피", "접속지", "클라이언트"]):
        return _client_ip_frequency_plan(query)

    command_hint = _detect_command(normalized)
    if command_hint and _looks_like_count_or_ranking(normalized):
        return _command_count_by_user_plan(query, command_hint)

    if any(token in normalized for token in ["많이", "가장", "상위", "top", "빈도", "횟수", "통계"]):
        return _command_frequency_plan(query)

    if _looks_like_user_list(normalized):
        if _mentions_chroma(normalized):
            return QueryPlan(
                tool=CHROMA_STATS_TOOL,
                reason="Chroma DB user list needs metadata aggregation, not similarity search",
                operation="chroma_user_list",
                params={"include_users": True},
            )
        return _user_list_plan(query)

    if command_hint:
        return _list_logs_plan(query, command_hint)

    if any(token in normalized for token in ["조회", "목록", "로그", "언제", "누가", "누구"]):
        return _list_logs_plan(query)

    return QueryPlan(
        tool=CHROMA_TOOL,
        reason="no exact aggregate or filter pattern detected",
        operation="semantic_search",
        params={"top_k": 8},
    )


def _is_semantic_search(normalized: str) -> bool:
    return any(
        token in normalized
        for token in ["비슷", "유사", "관련", "맥락", "의미", "패턴", "사례", "찾아줘"]
    ) and not _looks_like_count_or_ranking(normalized)


def _looks_like_count_or_ranking(normalized: str) -> bool:
    return any(token in normalized for token in ["가장", "많이", "상위", "top", "횟수", "몇", "통계", "빈도"])


def _mentions_chroma(normalized: str) -> bool:
    return any(
        token in normalized
        for token in ["chroma", "chroma_db", "chromadb", "vector db", "vectordb", "벡터db", "벡터 db"]
    )


def _looks_like_user_count(normalized: str) -> bool:
    user_tokens = ["사용자", "유저", "user", "users", "계정"]
    count_tokens = ["몇 명", "몇명", "사용자 수", "유저 수", "user count", "users count", "몇 개", "몇개", "총"]
    return any(token in normalized for token in user_tokens) and any(
        token in normalized for token in count_tokens
    )


def _looks_like_user_list(normalized: str) -> bool:
    user_tokens = ["사용자", "유저", "user", "users", "계정"]
    list_tokens = ["목록", "리스트", "명단", "누구", "누가", "보여", "알려"]
    return any(token in normalized for token in user_tokens) and any(
        token in normalized for token in list_tokens
    )


def _detect_days(query: str) -> Optional[int]:
    match = DAYS_RE.search(query)
    if not match:
        return None
    return max(1, int(match.group(1)))


def _detect_user(query: str) -> Optional[str]:
    match = USER_RE.search(query)
    return match.group(1) if match else None


def _detect_command(normalized: str) -> Optional[str]:
    for command in COMMAND_HINTS:
        if command.lower() in normalized:
            return command
    return None


def _where_clauses(params: Dict[str, Any]) -> List[str]:
    clauses = []
    if params.get("command_contains"):
        clauses.append(f"command LIKE '%{_escape_like(params['command_contains'])}%'")
    if params.get("user_name"):
        clauses.append(f"user_name = '{_escape_sql(params['user_name'])}'")
    if params.get("days"):
        clauses.append(
            "timestamp >= (SELECT MAX(timestamp) FROM command_history) "
            f"- INTERVAL {int(params['days'])} DAY"
        )
    return clauses


def _where_sql(params: Dict[str, Any]) -> str:
    clauses = _where_clauses(params)
    if not clauses:
        return ""
    return "WHERE " + " AND ".join(clauses)


def _command_count_by_user_plan(query: str, command_hint: str) -> QueryPlan:
    params = {
        "command_contains": command_hint,
        "days": _detect_days(query),
        "limit": 10,
    }
    sql = f"""
SELECT user_name, COUNT(*) AS command_count
FROM command_history
{_where_sql(params)}
GROUP BY user_name
ORDER BY command_count DESC, user_name ASC
LIMIT {params["limit"]}
""".strip()
    return QueryPlan(
        tool=MYSQL_TOOL,
        reason="command usage ranking needs exact aggregation",
        operation="command_count_by_user",
        sql=sql,
        params=params,
    )


def _user_count_plan(query: str) -> QueryPlan:
    params = {"days": _detect_days(query)}
    sql = f"""
SELECT COUNT(DISTINCT user_name) AS user_count
FROM command_history
{_where_sql(params)}
""".strip()
    return QueryPlan(
        tool=MYSQL_TOOL,
        reason="distinct user count needs exact aggregation",
        operation="user_count",
        sql=sql,
        params=params,
    )


def _user_list_plan(query: str) -> QueryPlan:
    params = {"days": _detect_days(query)}
    sql = f"""
SELECT user_name, COUNT(*) AS command_count
FROM command_history
{_where_sql(params)}
GROUP BY user_name
ORDER BY user_name ASC
""".strip()
    return QueryPlan(
        tool=MYSQL_TOOL,
        reason="user list needs exact grouping",
        operation="user_list",
        sql=sql,
        params=params,
    )


def _failed_count_by_user_plan(query: str) -> QueryPlan:
    params = {"days": _detect_days(query), "limit": 10}
    where = _where_sql(params)
    where = f"{where} AND exit_code != 0" if where else "WHERE exit_code != 0"
    sql = f"""
SELECT user_name, COUNT(*) AS failed_count
FROM command_history
{where}
GROUP BY user_name
ORDER BY failed_count DESC, user_name ASC
LIMIT {params["limit"]}
""".strip()
    return QueryPlan(
        tool=MYSQL_TOOL,
        reason="failure counts need exact aggregation on exit_code",
        operation="failed_count_by_user",
        sql=sql,
        params=params,
    )


def _command_frequency_plan(query: str) -> QueryPlan:
    params = {"user_name": _detect_user(query), "days": _detect_days(query), "limit": 10}
    sql = f"""
SELECT command, COUNT(*) AS command_count
FROM command_history
{_where_sql(params)}
GROUP BY command
ORDER BY command_count DESC, command ASC
LIMIT {params["limit"]}
""".strip()
    return QueryPlan(
        tool=MYSQL_TOOL,
        reason="command frequency needs exact aggregation",
        operation="command_frequency",
        sql=sql,
        params=params,
    )


def _client_ip_frequency_plan(query: str) -> QueryPlan:
    params = {"user_name": _detect_user(query), "days": _detect_days(query), "limit": 10}
    sql = f"""
SELECT client_ip, COUNT(*) AS access_count
FROM command_history
{_where_sql(params)}
GROUP BY client_ip
ORDER BY access_count DESC, client_ip ASC
LIMIT {params["limit"]}
""".strip()
    return QueryPlan(
        tool=MYSQL_TOOL,
        reason="IP usage needs exact aggregation",
        operation="client_ip_frequency",
        sql=sql,
        params=params,
    )


def _list_logs_plan(query: str, command_hint: Optional[str] = None) -> QueryPlan:
    params = {
        "command_contains": command_hint,
        "user_name": _detect_user(query),
        "days": _detect_days(query),
        "limit": 20,
    }
    sql = f"""
SELECT id, user_name, command, timestamp, current_dir, client_ip, server_ip, exit_code, session_id
FROM command_history
{_where_sql(params)}
ORDER BY timestamp DESC
LIMIT {params["limit"]}
""".strip()
    return QueryPlan(
        tool=MYSQL_TOOL,
        reason="explicit log lookup needs structured filtering",
        operation="list_logs",
        sql=sql,
        params=params,
    )


def _escape_sql(value: str) -> str:
    return value.replace("'", "''")


def _escape_like(value: str) -> str:
    return _escape_sql(value).replace("%", "\\%").replace("_", "\\_")
