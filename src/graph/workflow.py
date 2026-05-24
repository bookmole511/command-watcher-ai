# src/graph/workflow.py
"""
Command Watcher AI - LangGraph StateGraph 조립
Router → Conditional Routing → Specialized Agent
"""

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from typing import Dict, Any

# Agent 임포트
from src.agents.router import RouterAgent
from src.agents.anomaly_agent import AnomalyAgent
from src.agents.query_agent import QueryAgent
from src.agents.recommendation_agent import RecommendationAgent
from src.agents.compliance_agent import ComplianceAgent
from src.agents.incident_agent import IncidentAgent
from src.graph.state import create_initial_state


class CommandWatcherWorkflow:
    def __init__(self, llm):
        self.llm = llm
        
        # Agent 인스턴스 생성 (단일 LLM 공유)
        self.router = RouterAgent(llm)
        self.anomaly_agent = AnomalyAgent(llm)
        self.query_agent = QueryAgent(llm)
        self.recommendation_agent = RecommendationAgent(llm)
        self.compliance_agent = ComplianceAgent(llm)
        self.incident_agent = IncidentAgent(llm)
        
        # StateGraph 구축
        self.workflow = self._build_graph()
        self.app = self.workflow.compile(checkpointer=MemorySaver())
    
    def _build_graph(self):
        """StateGraph 조립"""
        graph = StateGraph(dict)
        
        # Node 추가
        graph.add_node("router", self.router)
        graph.add_node("anomaly_agent", self.anomaly_agent)
        graph.add_node("query_agent", self.query_agent)
        graph.add_node("recommendation_agent", self.recommendation_agent)
        graph.add_node("compliance_agent", self.compliance_agent)
        graph.add_node("incident_agent", self.incident_agent)
        
        # Entry Point
        graph.set_entry_point("router")
        
        # Conditional Edge: Router 판단에 따라 Agent로 분기
        def route_to_agent(state: Dict[str, Any]):
            intent = state.get("intent", "general")
            if intent == "anomaly":
                return "anomaly_agent"
            elif intent == "query":
                return "query_agent"
            elif intent == "recommendation":
                return "recommendation_agent"
            elif intent == "compliance":
                return "compliance_agent"
            elif intent == "incident":
                return "incident_agent"
            else:
                return "query_agent"  # default
        
        graph.add_conditional_edges(
            "router",
            route_to_agent,
            {
                "anomaly_agent": "anomaly_agent",
                "query_agent": "query_agent",
                "recommendation_agent": "recommendation_agent",
                "compliance_agent": "compliance_agent",
                "incident_agent": "incident_agent",
            }
        )
        
        # 모든 Agent는 END로 연결
        graph.add_edge("anomaly_agent", END)
        graph.add_edge("query_agent", END)
        graph.add_edge("recommendation_agent", END)
        graph.add_edge("compliance_agent", END)
        graph.add_edge("incident_agent", END)
        
        return graph
    
    def invoke(self, user_query: str, thread_id: str = "default"):
        """워크플로우 실행"""
        initial_state = create_initial_state(user_query)
        
        config = {"configurable": {"thread_id": thread_id}}
        
        result = self.app.invoke(initial_state, config)
        return result


# 테스트 실행용
if __name__ == "__main__":
    import os
    import sys
    from src.llm import create_chat_ollama

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    
    llm = create_chat_ollama(num_predict=128)
    
    workflow = CommandWatcherWorkflow(llm)
    
    test_queries = [
        "지난 7일간 sudo를 가장 많이 쓴 사람은 누구야?",
        "admin 계정이 이상 행동을 하는 것 같아",
        "user01에게 추천할 효율적인 명령어 패턴 알려줘",
        "rm -rf 명령어가 규정 위반인지 확인해줘",
        "어제 발생한 이상 로그의 근본 원인을 분석해줘"
    ]
    
    if len(sys.argv) > 1:
        test_queries = [" ".join(sys.argv[1:])]
    elif os.getenv("WORKFLOW_RUN_ALL_TESTS") != "1":
        test_queries = test_queries[:1]

    for i, q in enumerate(test_queries, 1):
        print(f"\nTest {i}: {q}")
        result = workflow.invoke(q)
        print(f"Intent: {result.get('intent')}")
        print(f"Response: {result.get('final_response')[:200]}..." if result.get('final_response') else "No response")
        print("-" * 80)
