# src/tools/mysql_tool.py
"""MySQL structured query tool."""

from typing import Any, Dict

import pandas as pd
from langchain_core.tools import tool
from sqlalchemy import create_engine, text

from src.config import DB_URL


engine = create_engine(DB_URL, pool_pre_ping=True)


@tool
def mysql_query_tool(sql_query: str) -> Dict[str, Any]:
    """
    Execute a MySQL query and return rows as dictionaries.

    Args:
        sql_query: SQL query to execute.

    Returns:
        Query result metadata and records, or an error payload.
    """
    try:
        with engine.connect() as conn:
            df = pd.read_sql(text(sql_query), conn)

        return {
            "success": True,
            "row_count": len(df),
            "data": df.to_dict(orient="records"),
            "columns": list(df.columns),
            "summary": f"{len(df)} rows returned",
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "SQL execution failed. Check the query and database connection.",
        }
