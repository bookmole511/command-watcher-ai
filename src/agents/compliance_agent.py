# src/agents/compliance_agent.py
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import AIMessage
from src.tools.mysql_tool import mysql_query_tool
from src.prompts import PROMPTS
from typing import Dict, Any

class ComplianceAgent:
    def __init__(self, llm):
        self.llm = llm
        self.prompt = ChatPromptTemplate.from_template(
            PROMPTS["compliance"]
            + "\n\nUser query:\n{query}\n\nAudit query result:\n{tool_result}\n\nAnswer based on the audit data."
        )
        self.mysql_tool = mysql_query_tool
    
    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        query = state["user_query"]
        tool_result = self.mysql_tool.invoke({"sql_query": "SELECT * FROM command_history WHERE exit_code != 0 OR command LIKE '%sudo%' LIMIT 30"})
        
        chain = self.prompt | self.llm
        response = chain.invoke({"query": query, "tool_result": tool_result})
        
        state["final_response"] = response.content
        state["messages"].append(AIMessage(content=response.content))
        return state
