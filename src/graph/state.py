# src/graph/state.py
"""
LangGraph에서 사용될 공유 State 정의
CPU 환경에 최적화된 가벼운 구조로 설계
"""

from typing import TypedDict, Annotated, List, Dict, Any, Optional
from operator import add
from langchain_core.messages import BaseMessage


class GraphState(TypedDict):
    """
    LangGraph 워크플로우에서 모든 Agent와 Node가 공유하는 상태
    """
    # 입력
    user_query: str                    # 사용자가 입력한 원본 쿼리
    
    # Router 판단 결과
    intent: str                        # "anomaly", "query", "recommendation", "compliance", "incident", "general"
    reasoning: str                     # Router가 판단한 근거 (디버깅용)
    selected_agent: str                # 실제 호출될 Agent 이름
    
    # 대화 기록 (메시지 누적)
    messages: Annotated[List[BaseMessage], add]
    
    # Tool 실행 결과 저장
    tool_results: Dict[str, Any]       # Tool별 결과 (Chroma, MySQL, Anomaly 등)
    
    # 최종 출력
    final_response: str                # 사용자에게 반환될 최종 답변
    
    # 추가 정보 (필요시 확장)
    error: Optional[str] = None        # 에러 발생 시 메시지
    execution_time: Optional[float] = None


# Helper 함수 (상태 초기화용)
def create_initial_state(user_query: str) -> GraphState:
    """새로운 쿼리에 대한 초기 State 생성"""
    from langchain_core.messages import HumanMessage
    
    return {
        "user_query": user_query,
        "intent": "",
        "reasoning": "",
        "selected_agent": "",
        "messages": [HumanMessage(content=user_query)],
        "tool_results": {},
        "final_response": "",
        "error": None,
        "execution_time": None,
    }