from dataclasses import asdict
from typing import Any, Dict

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate

from src.agents.query_planner import MYSQL_TOOL, choose_query_plan
from src.prompts import PROMPTS
from src.tools.chroma_retriever import chroma_retriever
from src.tools.mysql_tool import mysql_query_tool


QUERY_RESPONSE_POLICY = """
Response language policy:
- Answer only in Korean or English. Match the user's language when it is clearly Korean or English; otherwise use Korean.
- Do not output broken encoding, mojibake, Chinese, Japanese, or mixed-language filler text.
- Preserve exact command strings, paths, usernames, IP addresses, timestamps, SQL snippets, and numeric values as data.
- For aggregate results, answer with the key result first, then brief supporting rows.
"""


class QueryAgent:
    def __init__(self, llm):
        self.llm = llm
        self.chroma_prompt = ChatPromptTemplate.from_template(
            QUERY_RESPONSE_POLICY
            + "\n"
            + PROMPTS["query"]
            + "\n\nUser query:\n{query}"
            + "\n\nChroma results:\n{chroma_results}"
            + "\n\nAnswer based on the retrieved results."
        )
        self.mysql_prompt = ChatPromptTemplate.from_template(
            QUERY_RESPONSE_POLICY
            + "\n"
            + PROMPTS["query"]
            + "\n\nUser query:\n{query}"
            + "\n\nSelected tool: MySQL"
            + "\nReason: {plan_reason}"
            + "\nSQL:\n{sql}"
            + "\n\nMySQL result:\n{mysql_result}"
            + "\n\nAnswer from the SQL result. If the result contains an error, say that the query failed and include the error."
        )
        self.chroma_tool = chroma_retriever
        self.mysql_tool = mysql_query_tool

    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        query = state["user_query"]
        plan = choose_query_plan(query)
        state.setdefault("tool_results", {})["query_plan"] = asdict(plan)

        if plan.tool == MYSQL_TOOL:
            mysql_result = self.mysql_tool.invoke({"sql_query": plan.sql})
            state["tool_results"]["mysql"] = mysql_result

            chain = self.mysql_prompt | self.llm
            response = chain.invoke(
                {
                    "query": query,
                    "plan_reason": plan.reason,
                    "sql": plan.sql,
                    "mysql_result": mysql_result,
                }
            )
        else:
            chroma_results = self.chroma_tool.invoke(
                {"query": query, "top_k": plan.params.get("top_k", 8)}
            )
            state["tool_results"]["chroma"] = chroma_results

            chain = self.chroma_prompt | self.llm
            response = chain.invoke(
                {
                    "query": query,
                    "chroma_results": chroma_results,
                }
            )

        state["final_response"] = response.content
        state.setdefault("messages", []).append(AIMessage(content=response.content))

        return state
