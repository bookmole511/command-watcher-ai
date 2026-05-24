# src/tools/anomaly_detector.py
"""Isolation Forest based anomaly detection tool."""

from typing import Any, Dict, Optional

import pandas as pd
from langchain_core.tools import tool
from sklearn.ensemble import IsolationForest
from sqlalchemy import create_engine, text

from src.config import DB_URL


@tool
def anomaly_detection_tool(
    user_name: Optional[str] = None,
    days: int = 30,
) -> Dict[str, Any]:
    """
    Detect anomalous command behavior from command history aggregates.

    Args:
        user_name: Optional user filter.
        days: Number of recent days to analyze.

    Returns:
        Anomaly detection result payload.
    """
    try:
        engine = create_engine(DB_URL)

        safe_days = max(1, int(days))
        query = f"""
            SELECT user_name, COUNT(*) as cmd_count,
                   COUNT(DISTINCT command) as unique_cmd,
                   AVG(exit_code) as avg_exit_code
            FROM command_history
            WHERE timestamp >= NOW() - INTERVAL {safe_days} DAY
        """
        params: Dict[str, Any] = {}

        if user_name:
            query += " AND user_name = :user_name"
            params["user_name"] = user_name

        query += " GROUP BY user_name"

        df = pd.read_sql(text(query), engine, params=params)

        if len(df) < 3:
            return {"message": "Not enough data to run anomaly detection."}

        features = df[["cmd_count", "unique_cmd", "avg_exit_code"]]

        model = IsolationForest(contamination=0.1, random_state=42)
        df["anomaly_score"] = model.fit_predict(features)
        df["is_anomaly"] = df["anomaly_score"] == -1

        anomalies = df[df["is_anomaly"]].to_dict(orient="records")

        return {
            "total_users": len(df),
            "anomaly_count": len(anomalies),
            "anomalies": anomalies,
            "message": f"Detected {len(anomalies)} anomalous users in the last {safe_days} days.",
        }

    except Exception as e:
        return {"error": str(e)}
