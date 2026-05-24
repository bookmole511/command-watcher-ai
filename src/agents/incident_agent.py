# src/agents/incident_agent.py
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import AIMessage
from src.tools.chroma_retriever import chroma_retriever
from src.tools.mysql_tool import mysql_query_tool
from src.prompts import PROMPTS
from typing import Dict, Any

class IncidentAgent:
    def __init__(self, llm):
        self.llm = llm
        self.prompt = ChatPromptTemplate.from_template(
            PROMPTS["incident"]
            + "\n\nUser query:\n{query}\n\nChroma result:\n{chroma_result}\n\nAnswer based on the retrieved incident context."
        )
        self.chroma = chroma_retriever
        self.mysql = mysql_query_tool
    
    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        query = state["user_query"]
        chroma_result = self.chroma.invoke({"query": query})
        
        chain = self.prompt | self.llm
        response = chain.invoke({"query": query, "chroma_result": chroma_result})
        
        state["final_response"] = response.content
        state["messages"].append(AIMessage(content=response.content))
        return state
