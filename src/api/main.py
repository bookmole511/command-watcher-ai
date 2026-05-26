# src/api/main.py
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from typing import Optional
import time
from pathlib import Path

from src.config import (
    LLM_MODEL,
    LLM_NUM_CTX,
    LLM_NUM_PREDICT,
    LLM_NUM_THREAD,
    LLM_TEMPERATURE,
)
from src.graph.workflow import CommandWatcherWorkflow
from src.llm import create_chat_ollama

app = FastAPI(title="Command Watcher AI")

# 전역 workflow
workflow = None

@app.on_event("startup")
async def startup_event():
    global workflow
    llm = create_chat_ollama(
        model=LLM_MODEL,
        temperature=LLM_TEMPERATURE,
        num_ctx=LLM_NUM_CTX,
        num_thread=LLM_NUM_THREAD,
        num_predict=LLM_NUM_PREDICT,
        base_url="http://127.0.0.1:11434"   # ← 여기 추가 (가장 중요!)
    )
    workflow = CommandWatcherWorkflow(llm)
    print(f"🚀 Command Watcher AI 서버 시작됨 (Model: {LLM_MODEL})")


class QueryRequest(BaseModel):
    query: str
    thread_id: Optional[str] = "default"


@app.get("/", response_class=FileResponse)
async def home():
    """현대적인 Command Watcher AI UI"""
    template_path = Path(__file__).parent.parent.parent / "templates" / "index.html"
    if template_path.exists():
        return FileResponse(str(template_path), media_type="text/html")
    return HTMLResponse("<h1>UI 템플릿을 찾을 수 없습니다. templates/index.html 파일을 확인하세요.</h1>")


@app.post("/query")
async def query(request: QueryRequest):
    start_time = time.time()
    try:
        if not request.query or not request.query.strip():
            raise HTTPException(status_code=400, detail="쿼리를 입력해주세요.")
        
        result = workflow.invoke(
            user_query=request.query.strip(),
            thread_id=request.thread_id
        )
        
        return {
            "success": True,
            "intent": result.get("intent", "unknown"),
            "response": result.get("final_response", "응답을 생성할 수 없습니다."),
            "execution_time": round(time.time() - start_time, 2),
            # 새로운 UI의 디버그 패널을 위한 추가 데이터
            "tool_results": result.get("tool_results"),
            "structured_response": result.get("structured_response"),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "execution_time": round(time.time() - start_time, 2),
            "tool_results": None,
            "structured_response": None,
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000, reload=True)
