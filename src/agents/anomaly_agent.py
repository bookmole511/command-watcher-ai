"""Anomaly analysis agent.

This agent keeps the mandatory structured output deterministic. The existing
IsolationForest tool is used as the primary model signal, and small MySQL
aggregates add command/session context for analyst-friendly triage.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import re
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field

from src.tools.anomaly_detector import anomaly_detection_tool
from src.tools.mysql_tool import mysql_query_tool


class AnomalyResult(BaseModel):
    anomaly_score: float = Field(..., ge=0.0, le=1.0)
    top_anomalous_users: List[Dict[str, Any]]
    top_anomalous_commands: List[Dict[str, Any]]
    suspicious_sessions: List[Dict[str, Any]]
    summary: str
    recommendations: List[str]
    timestamp: str


DAY_PATTERNS = [
    re.compile(r"(\d+)\s*\uC77C"),
    re.compile(r"(\d+)\s*days?", re.IGNORECASE),
    re.compile(
        r"(?:last|past|recent|\uCD5C\uADFC|\uC9C0\uB09C)\s*(\d+)",
        re.IGNORECASE,
    ),
]
USER_RE = re.compile(r"\b(admin|root|user[A-Za-z0-9_]+)\b", re.IGNORECASE)

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


class AnomalyAgent:
    def __init__(
        self,
        llm: Any,
        anomaly_tool: Any = anomaly_detection_tool,
        mysql_tool: Any = mysql_query_tool,
    ):
        self.llm = llm
        self.anomaly_tool = anomaly_tool
        self.mysql_tool = mysql_tool

    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        query = state["user_query"]
        days = _detect_days(query)
        user_name = _detect_user(query)

        detection_result = self.anomaly_tool.invoke(
            {"user_name": user_name, "days": days}
        )
        user_risk_result = self.mysql_tool.invoke(
            {"sql_query": _user_risk_sql(days=days, user_name=user_name)}
        )
        command_result = self.mysql_tool.invoke(
            {"sql_query": _command_risk_sql(days=days, user_name=user_name)}
        )
        session_result = self.mysql_tool.invoke(
            {"sql_query": _session_risk_sql(days=days, user_name=user_name)}
        )

        structured_result = _build_result(
            detection_result=detection_result,
            user_risk_result=user_risk_result,
            command_result=command_result,
            session_result=session_result,
        )
        result_payload = _model_to_dict(structured_result)

        state.setdefault("tool_results", {})["anomaly"] = {
            "params": {"user_name": user_name, "days": days},
            "isolation_forest": _json_safe(detection_result),
            "user_risk": _json_safe(user_risk_result),
            "command_risk": _json_safe(command_result),
            "session_risk": _json_safe(session_result),
            "structured_result": result_payload,
        }
        state["structured_response"] = result_payload
        state["final_response"] = json.dumps(result_payload, ensure_ascii=False)
        state.setdefault("messages", []).append(
            AIMessage(content=state["final_response"])
        )

        return state


def _detect_days(query: str) -> int:
    for pattern in DAY_PATTERNS:
        match = pattern.search(query)
        if match:
            return max(1, min(int(match.group(1)), 365))
    return 30


def _detect_user(query: str) -> Optional[str]:
    match = USER_RE.search(query)
    return match.group(1) if match else None


def _build_result(
    detection_result: Dict[str, Any],
    user_risk_result: Dict[str, Any],
    command_result: Dict[str, Any],
    session_result: Dict[str, Any],
) -> AnomalyResult:
    top_users = _top_users(detection_result, user_risk_result)
    top_commands = _rows(command_result, limit=10)
    suspicious_sessions = _rows(session_result, limit=10)

    score = _overall_score(detection_result, top_users, top_commands, suspicious_sessions)
    summary = _summary(detection_result, score, top_users, top_commands, suspicious_sessions)
    recommendations = _recommendations(score, top_users, top_commands, suspicious_sessions)

    return AnomalyResult(
        anomaly_score=score,
        top_anomalous_users=top_users,
        top_anomalous_commands=top_commands,
        suspicious_sessions=suspicious_sessions,
        summary=summary,
        recommendations=recommendations,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def _top_users(
    detection_result: Dict[str, Any], user_risk_result: Dict[str, Any]
) -> List[Dict[str, Any]]:
    by_user: Dict[str, Dict[str, Any]] = {}

    for row in _rows(user_risk_result, limit=20):
        user_name = str(row.get("user_name", ""))
        if not user_name:
            continue
        item = dict(row)
        item["isolation_forest_anomaly"] = False
        item["risk_score"] = _user_risk_score(item, model_anomaly=False)
        by_user[user_name] = item

    for row in detection_result.get("anomalies", []) or []:
        item = _json_safe(row)
        user_name = str(item.get("user_name", ""))
        if not user_name:
            continue

        merged = by_user.get(user_name, {})
        merged.update(item)
        merged["isolation_forest_anomaly"] = True
        merged["risk_score"] = _user_risk_score(merged, model_anomaly=True)
        by_user[user_name] = merged

    return sorted(
        by_user.values(),
        key=lambda item: (
            float(item.get("risk_score", 0.0)),
            int(_number(item.get("risk_hits"))),
            int(_number(item.get("failure_count"))),
            int(_number(item.get("cmd_count"))),
        ),
        reverse=True,
    )[:10]


def _overall_score(
    detection_result: Dict[str, Any],
    top_users: List[Dict[str, Any]],
    top_commands: List[Dict[str, Any]],
    suspicious_sessions: List[Dict[str, Any]],
) -> float:
    total_users = max(0, int(_number(detection_result.get("total_users"))))
    anomaly_count = max(0, int(_number(detection_result.get("anomaly_count"))))

    model_signal = (anomaly_count / total_users) if total_users else 0.0
    user_signal = max((float(user.get("risk_score", 0.0)) for user in top_users), default=0.0)
    command_signal = min(1.0, len(top_commands) / 10.0)
    session_signal = min(1.0, len(suspicious_sessions) / 10.0)

    score = (
        (0.35 * model_signal)
        + (0.35 * user_signal)
        + (0.15 * command_signal)
        + (0.15 * session_signal)
    )
    return round(_clamp(score), 3)


def _user_risk_score(row: Dict[str, Any], model_anomaly: bool) -> float:
    score = 0.55 if model_anomaly else 0.0
    score += min(_number(row.get("risk_hits")) / 5.0, 1.0) * 0.20
    score += min(_number(row.get("failure_count")) / 10.0, 1.0) * 0.12
    score += min(_number(row.get("unique_cmd")) / 20.0, 1.0) * 0.08
    score += min(_number(row.get("cmd_count")) / 100.0, 1.0) * 0.05
    return round(_clamp(score), 3)


def _summary(
    detection_result: Dict[str, Any],
    score: float,
    top_users: List[Dict[str, Any]],
    top_commands: List[Dict[str, Any]],
    suspicious_sessions: List[Dict[str, Any]],
) -> str:
    if detection_result.get("error"):
        return f"Anomaly analysis failed: {detection_result['error']}"

    if "Not enough data" in str(detection_result.get("message", "")):
        return "Not enough user-level history is available to run reliable anomaly detection."

    level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
    user_count = len([u for u in top_users if u.get("isolation_forest_anomaly")])
    return (
        f"Overall anomaly risk is {level} ({score:.3f}). "
        f"IsolationForest flagged {user_count} user(s); "
        f"{len(top_commands)} risky command pattern(s) and "
        f"{len(suspicious_sessions)} suspicious session(s) need review."
    )


def _recommendations(
    score: float,
    top_users: List[Dict[str, Any]],
    top_commands: List[Dict[str, Any]],
    suspicious_sessions: List[Dict[str, Any]],
) -> List[str]:
    recommendations: List[str] = []

    if top_users:
        users = ", ".join(str(user.get("user_name")) for user in top_users[:3])
        recommendations.append(f"Review recent command history and access context for: {users}.")

    if top_commands:
        recommendations.append(
            "Validate risky command usage, especially sudo, destructive file operations, and network download commands."
        )

    if suspicious_sessions:
        recommendations.append(
            "Correlate suspicious sessions with client IP, server IP, login records, and change tickets."
        )

    if score >= 0.7:
        recommendations.append(
            "Temporarily increase monitoring on flagged users and consider credential/session revocation if activity is unauthorized."
        )
    elif score >= 0.4:
        recommendations.append(
            "Run a focused analyst review before closing this as expected administrative activity."
        )
    else:
        recommendations.append(
            "Keep normal monitoring active and use a wider time window if the query expected stronger signals."
        )

    return recommendations


def _rows(result: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
    if not result or result.get("success") is False:
        return []

    rows = result.get("data")
    if rows is None and "anomalies" in result:
        rows = result.get("anomalies")
    if not isinstance(rows, list):
        return []

    return [_json_safe(row) for row in rows[:limit] if isinstance(row, dict)]


def _user_risk_sql(days: int, user_name: Optional[str]) -> str:
    return f"""
SELECT
  user_name,
  COUNT(*) AS cmd_count,
  COUNT(DISTINCT command) AS unique_cmd,
  SUM(CASE WHEN exit_code != 0 THEN 1 ELSE 0 END) AS failure_count,
  SUM(CASE WHEN {_risk_condition_sql()} THEN 1 ELSE 0 END) AS risk_hits,
  COUNT(DISTINCT session_id) AS session_count,
  MAX(timestamp) AS last_seen
FROM command_history
WHERE {_where_sql(days, user_name)}
GROUP BY user_name
ORDER BY risk_hits DESC, failure_count DESC, cmd_count DESC, user_name ASC
LIMIT 10
""".strip()


def _command_risk_sql(days: int, user_name: Optional[str]) -> str:
    return f"""
SELECT
  command,
  COUNT(*) AS command_count,
  COUNT(DISTINCT user_name) AS user_count,
  SUM(CASE WHEN exit_code != 0 THEN 1 ELSE 0 END) AS failure_count,
  SUM(CASE WHEN {_risk_condition_sql()} THEN 1 ELSE 0 END) AS risk_hits,
  MAX(timestamp) AS last_seen
FROM command_history
WHERE {_where_sql(days, user_name)}
GROUP BY command
HAVING risk_hits > 0 OR failure_count > 0
ORDER BY risk_hits DESC, failure_count DESC, command_count DESC, command ASC
LIMIT 10
""".strip()


def _session_risk_sql(days: int, user_name: Optional[str]) -> str:
    return f"""
SELECT
  session_id,
  user_name,
  client_ip,
  server_ip,
  COUNT(*) AS command_count,
  COUNT(DISTINCT command) AS unique_command_count,
  SUM(CASE WHEN exit_code != 0 THEN 1 ELSE 0 END) AS failure_count,
  SUM(CASE WHEN {_risk_condition_sql()} THEN 1 ELSE 0 END) AS risk_hits,
  MIN(timestamp) AS first_seen,
  MAX(timestamp) AS last_seen
FROM command_history
WHERE {_where_sql(days, user_name)}
GROUP BY session_id, user_name, client_ip, server_ip
HAVING risk_hits > 0 OR failure_count > 0 OR command_count >= 20 OR unique_command_count >= 10
ORDER BY risk_hits DESC, failure_count DESC, command_count DESC, last_seen DESC
LIMIT 10
""".strip()


def _where_sql(days: int, user_name: Optional[str]) -> str:
    clauses = [
        "timestamp >= (SELECT MAX(timestamp) FROM command_history) "
        f"- INTERVAL {max(1, int(days))} DAY"
    ]
    if user_name:
        clauses.append(f"user_name = '{_escape_sql(user_name)}'")
    return " AND ".join(clauses)


def _risk_condition_sql() -> str:
    return " OR ".join(RISK_COMMAND_CONDITIONS)


def _escape_sql(value: str) -> str:
    return value.replace("'", "''")


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(number) or math.isinf(number):
        return 0.0
    return number


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    return value


def _model_to_dict(model: BaseModel) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()
