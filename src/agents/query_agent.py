from dataclasses import asdict
from typing import Any, Dict

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate

from src.agents.query_planner import CHROMA_STATS_TOOL, MYSQL_TOOL, choose_query_plan
from src.prompts import PROMPTS
from src.tools.chroma_retriever import chroma_retriever
from src.tools.chroma_stats import chroma_user_summary
from src.tools.mysql_tool import mysql_query_tool


QUERY_RESPONSE_POLICY = """
Response language & formatting policy:
- Answer only in Korean or English. Match the user's language when it is clearly Korean or English; otherwise use Korean.
- Do not output broken encoding, mojibake, Chinese, Japanese, or mixed-language filler text.
- Preserve exact command strings, paths, usernames, IP addresses, timestamps, SQL snippets, and numeric values as data.
- For aggregate results, answer with the key result first, then brief supporting rows.
- **Always format the final answer in Markdown**:
  - Use headings (##, ###) for sections when the result is complex
  - Use bullet points or numbered lists for multiple items
  - Use `inline code` for commands, paths, and important values
  - Use Markdown tables (`|`) for statistics or comparison results when appropriate
  - Keep the response clean and easy to read in the UI
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
            + "\n\n위 결과를 바탕으로 **Markdown 형식**으로 깔끔하게 답변하세요."
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
            + "\n\n위 결과를 바탕으로 **Markdown 형식**으로 깔끔하게 답변하세요. (오류 발생 시 명확히 표시)"
        )
        self.chroma_tool = chroma_retriever
        self.chroma_stats_tool = chroma_user_summary
        self.mysql_tool = mysql_query_tool

    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        query = state["user_query"]
        plan = choose_query_plan(query)
        state.setdefault("tool_results", {})["query_plan"] = asdict(plan)

        if plan.tool == CHROMA_STATS_TOOL:
            chroma_stats = self.chroma_stats_tool.invoke(
                {"include_users": plan.params.get("include_users", True)}
            )
            state["tool_results"]["chroma_stats"] = chroma_stats
            response_content = _format_chroma_user_summary(chroma_stats)
            response = AIMessage(content=response_content)

        elif plan.tool == MYSQL_TOOL:
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


def _format_chroma_user_summary(result: Dict[str, Any]) -> str:
    if not result.get("success"):
        return (
            "## Chroma DB 사용자 요약\n\n"
            f"- 조회 실패: {result.get('message', 'Chroma metadata aggregation failed.')}\n"
            f"- 오류: `{result.get('error', 'unknown')}`"
        )

    lines = [
        "## Chroma DB 사용자 요약",
        "",
        f"- 사용자 수: **{result.get('user_count', 0)}명**",
        f"- 문서 수: `{result.get('document_count', 0)}`",
        f"- 컬렉션: `{result.get('collection')}`",
    ]

    users = result.get("users") or []
    if users:
        lines.extend(["", "### 사용자 목록", ", ".join(f"`{user}`" for user in users)])

    return "\n".join(lines)
