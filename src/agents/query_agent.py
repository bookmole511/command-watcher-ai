# src/agents/query_agent.py
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import AIMessage
from src.tools.chroma_retriever import chroma_retriever
from src.tools.mysql_tool import mysql_query_tool
from src.prompts import PROMPTS
from typing import Dict, Any

class QueryAgent:
    def __init__(self, llm):
        self.llm = llm
        self.prompt = ChatPromptTemplate.from_template(
            PROMPTS["query"]
            + "\n\nUser query:\n{query}\n\nChroma results:\n{chroma_results}\n\nAnswer based on the retrieved results."
        )
        self.chroma_tool = chroma_retriever
        self.mysql_tool = mysql_query_tool
    
    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        query = state["user_query"]
        
        # Chroma 검색 (의미 검색)
        chroma_results = self.chroma_tool.invoke({"query": query, "top_k": 8})
        state["tool_results"]["chroma"] = chroma_results
        
        # LLM 판단 후 필요시 MySQL Tool 추가 호출
        chain = self.prompt | self.llm
        response = chain.invoke({
            "query": query,
            "chroma_results": chroma_results
        })
        
        state["final_response"] = response.content
        state["messages"].append(AIMessage(content=response.content))
        
        return state
