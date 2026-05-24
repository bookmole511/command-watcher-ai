# src/agents/recommendation_agent.py
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import AIMessage
from src.tools.mysql_tool import mysql_query_tool
from src.prompts import PROMPTS
from typing import Dict, Any

class RecommendationAgent:
    def __init__(self, llm):
        self.llm = llm
        self.prompt = ChatPromptTemplate.from_template(
            PROMPTS["recommendation"]
            + "\n\nUser query:\n{query}\n\nCommand frequency result:\n{tool_result}\n\nAnswer based on the command history."
        )
        self.mysql_tool = mysql_query_tool
    
    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        query = state["user_query"]
        
        # 사용자 패턴 분석용 MySQL 조회
        sql = "SELECT user_name, command, COUNT(*) as freq FROM command_history GROUP BY user_name, command ORDER BY freq DESC LIMIT 20"
        tool_result = self.mysql_tool.invoke({"sql_query": sql})
        state["tool_results"]["recommendation"] = tool_result
        
        chain = self.prompt | self.llm
        response = chain.invoke({
            "query": query,
            "tool_result": tool_result
        })
        
        state["final_response"] = response.content
        state["messages"].append(AIMessage(content=response.content))
        
        return state
