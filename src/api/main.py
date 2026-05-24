# src/api/main.py
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
import time

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


@app.get("/", response_class=HTMLResponse)
async def home():
    """간단한 웹 UI"""
    html_content = """
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Command Watcher AI</title>
        <style>
            body { font-family: 'Malgun Gothic', sans-serif; margin: 30px; background: #f0f2f5; }
            .container { max-width: 900px; margin: 0 auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }
            h1 { color: #1e3a8a; }
            textarea { width: 100%; height: 130px; padding: 15px; border: 2px solid #ddd; border-radius: 10px; font-size: 16px; }
            button { padding: 14px 28px; font-size: 17px; background: #1e40af; color: white; border: none; border-radius: 8px; cursor: pointer; margin-top: 10px; }
            button:hover { background: #1e3a8a; }
            #result { margin-top: 25px; padding: 20px; border: 1px solid #ddd; border-radius: 10px; min-height: 250px; background: #fafafa; white-space: pre-wrap; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🛠️ Command Watcher AI</h1>
            <p>서버 명령어 이력을 자연어로 분석해드립니다.</p>
            
            <textarea id="query" placeholder="예시) 지난 7일간 sudo를 가장 많이 사용한 사람은 누구야?"></textarea>
            <br><br>
            <button onclick="sendQuery()">🔍 분석하기</button>
            
            <div id="result"></div>
        </div>

        <script>
            async function sendQuery() {
                const queryText = document.getElementById('query').value.trim();
                const resultDiv = document.getElementById('result');
                
                if (!queryText) {
                    alert("질문을 입력해주세요.");
                    return;
                }
                
                resultDiv.innerHTML = "<p><strong>분석 중입니다...</strong> 잠시만 기다려주세요.</p>";
                
                try {
                    const response = await fetch('/query', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ query: queryText })
                    });
                    
                    const data = await response.json();
                    
                    if (data.success) {
                        resultDiv.innerHTML = `
                            <strong>Intent:</strong> ${data.intent}<br><br>
                            <strong>답변:</strong><br>
                            ${data.response}
                            <hr>
                            <small>⏱ 소요시간: ${data.execution_time}초</small>
                        `;
                    } else {
                        resultDiv.innerHTML = `<span style="color:red;">❌ 오류: ${data.error}</span>`;
                    }
                } catch (e) {
                    resultDiv.innerHTML = `<span style="color:red;">❌ 서버와 연결할 수 없습니다.</span>`;
                }
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


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
            "execution_time": round(time.time() - start_time, 2)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "execution_time": round(time.time() - start_time, 2)
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000, reload=True)
