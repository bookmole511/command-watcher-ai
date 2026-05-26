# src/utils.py
"""
Command Watcher AI - 공용 유틸리티
Structured Output 등 공통 컴포넌트 관리
"""

from pydantic import BaseModel, Field
from typing import Literal


class AgentIntent(BaseModel):
    """Router가 판단하는 Intent 구조"""
    intent: Literal[
        "anomaly", 
        "query", 
        "recommendation", 
        "compliance", 
        "incident", 
        "general"
    ] = Field(..., description="사용자 쿼리의 주요 의도")
    
    reasoning: str = Field(..., description="판단 근거 설명")


# 실행 경로 문제 해결용 (선택)
import sys
from pathlib import Path
from datetime import datetime
from typing import Any
import json


def add_project_root_to_path():
    """프로젝트 루트를 Python Path에 추가"""
    project_root = Path(__file__).parent.parent.parent.absolute()
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


def json_safe(obj: Any) -> Any:
    """
    pandas Timestamp, numpy scalar, datetime 등을 포함한 객체를
    JSON 직렬화 가능한 형태로 안전하게 변환합니다.
    (AnomalyAgent / RecommendationAgent 등에서 사용)
    """
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(item) for item in obj]
    if isinstance(obj, set):
        return [json_safe(item) for item in obj]

    # pandas Timestamp / datetime
    if hasattr(obj, "isoformat"):  # datetime, pd.Timestamp 등
        try:
            return obj.isoformat()
        except Exception:
            return str(obj)

    # numpy scalar (np.int64, np.float64 등)
    if hasattr(obj, "item"):
        try:
            return obj.item()
        except Exception:
            pass

    # 마지막 시도: 이미 직렬화 가능한지 확인
    try:
        json.dumps(obj)
        return obj
    except (TypeError, OverflowError, ValueError):
        return str(obj)


def safe_json_dumps(obj: Any, **kwargs) -> str:
    """json_safe를 적용한 후 json.dumps"""
    return json.dumps(json_safe(obj), ensure_ascii=False, **kwargs)