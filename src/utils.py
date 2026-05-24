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

def add_project_root_to_path():
    """프로젝트 루트를 Python Path에 추가"""
    project_root = Path(__file__).parent.parent.parent.absolute()
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))