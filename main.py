# main.py (프로젝트 루트)
"""
Command Watcher AI - 엔트리 포인트
"""

from src.api.main import app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000, reload=True)