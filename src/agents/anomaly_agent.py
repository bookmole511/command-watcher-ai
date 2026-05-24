# src/agents/anomaly_agent.py
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import AIMessage
from src.tools.anomaly_detector import anomaly_detection_tool
from src.prompts import PROMPTS
from typing import Dict, Any

class AnomalyAgent:
    def __init__(self, llm):
        self.llm = llm
        self.prompt = ChatPromptTemplate.from_template(
            PROMPTS["anomaly"]
            + "\n\nUser query:\n{query}\n\nAnomaly detection result:\n{tool_result}\n\nAnswer based on the detection result."
        )
        self.tool = anomaly_detection_tool
    
    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        query = state["user_query"]
        
        # Tool 호출
        tool_result = self.tool.invoke({"user_name": None, "days": 30})
        state["tool_results"]["anomaly"] = tool_result
        
        # LLM 분석
        chain = self.prompt | self.llm
        response = chain.invoke({
            "query": query,
            "tool_result": tool_result
        })
        
        state["final_response"] = response.content
        state["messages"].append(AIMessage(content=response.content))
        
        return state
