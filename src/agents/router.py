# src/agents/router.py
"""
Router Agent
사용자 쿼리를 분석하여 적절한 Specialized Agent로 라우팅
Structured Output + Tool Calling 없이 Pure LLM 판단
"""

from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama
from langchain_core.output_parsers import PydanticOutputParser
from src.utils import AgentIntent
from src.prompts import PROMPTS   # 아직 prompts.py가 완성되지 않았으므로 아래에서 임시 정의
from typing import Dict, Any

# ==================== Router Prompt (중앙 관리 예정) ====================
ROUTER_PROMPT = """당신은 명령어 이력 분석 시스템의 Router입니다.
사용자의 질문을 분석하여 가장 적합한 Agent로 라우팅해야 합니다.

가능한 Intent 목록:
- anomaly: 이상 행동 탐지, 보안 이상징후 분석 요청
- query: 단순 로그 조회, 특정 조건 검색, 통계 요청
- recommendation: 사용자별 명령어 추천, 워크플로우 최적화 요청
- compliance: 컴플라이언스, 감사, 규정 준수 관련 요청
- incident: 인시던트 조사, 근본 원인 분석, 특정 사건 조사 요청
- general: 일반적인 질문, 시스템 설명, 기타

쿼리를 분석하고 아래 JSON 형식으로만 응답하세요.
User query:
{query}

{format_instructions}
"""

class RouterAgent:
    def __init__(self, llm: ChatOllama):
        self.llm = llm
        
        # Structured Output 설정
        self.parser = PydanticOutputParser(pydantic_object=AgentIntent)
        
        self.prompt = ChatPromptTemplate.from_template(ROUTER_PROMPT)
        
        # Chain 구성
        self.chain = (
            self.prompt
            | self.llm
            | self.parser
        )
    
    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Router 실행"""
        user_query = state["user_query"]
        
        try:
            # Router 실행
            result = self.chain.invoke({
                "query": user_query,
                "format_instructions": self.parser.get_format_instructions()
            })
            
            # State 업데이트
            state["intent"] = result.intent
            state["reasoning"] = result.reasoning
            state["selected_agent"] = f"{result.intent}_agent"
            
            # 메시지 추가
            from langchain_core.messages import AIMessage
            state["messages"].append(
                AIMessage(content=f"Intent: {result.intent}\nReasoning: {result.reasoning}")
            )
            
            print(f"Router intent: {result.intent} (reason: {result.reasoning[:80]}...)")
            
        except Exception as e:
            state["error"] = f"Router 오류: {str(e)}"
            state["intent"] = "general"
            state["selected_agent"] = "general_agent"
        
        return state


# 테스트용 (직접 실행 가능)
if __name__ == "__main__":
    import sys
    from src.llm import create_chat_ollama

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    
    llm = create_chat_ollama(num_predict=256)
    router = RouterAgent(llm)
    
    test_queries = [
        "지난 7일간 sudo를 가장 많이 사용한 사람은 누구야?",
        "admin 계정이 이상하게 행동하는 것 같아",
        "user01에게 추천할 효율적인 명령어 워크플로우 알려줘",
        "이 로그가 규정 위반인지 확인해줘",
        "어제 발생한 rm -rf 사건의 근본 원인을 분석해"
    ]
    
    for q in test_queries:
        state = {"user_query": q}
        result = router(state)
        print("-" * 60)
