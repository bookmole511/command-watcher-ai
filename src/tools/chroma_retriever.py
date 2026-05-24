# src/tools/chroma_retriever.py
"""
Chroma Vector DB Retriever Tool
자연어 의미 검색 전문 Tool
"""

import os
from typing import List, Dict, Any

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("DISABLE_SAFETENSORS_CONVERSION", "1")
os.environ.setdefault("TQDM_DISABLE", "1")

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.tools import tool

PERSIST_DIRECTORY = "./chroma_db"
COLLECTION_NAME = "command_logs"
EMBEDDING_MODEL = "BAAI/bge-m3"

@tool
def chroma_retriever(query: str, top_k: int = 6) -> List[Dict[str, Any]]:
    """
    자연어로 명령어 로그를 의미 기반 검색
    
    Args:
        query: 검색할 자연어 쿼리
        top_k: 반환할 결과 개수 (기본 6)
    
    Returns:
        관련 로그 리스트 (metadata 포함)
    """
    try:
        embeddings = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            model_kwargs={
                "device": "cpu",
                "local_files_only": True,
                "model_kwargs": {"use_safetensors": False},
            },
            encode_kwargs={"normalize_embeddings": True}
        )
        
        vectorstore = Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=embeddings,
            persist_directory=PERSIST_DIRECTORY
        )
        
        results = vectorstore.similarity_search_with_score(query, k=top_k)
        
        formatted_results = []
        for doc, score in results:
            formatted_results.append({
                "content": doc.page_content,
                "metadata": doc.metadata,
                "similarity_score": float(score)
            })
        
        return formatted_results
        
    except Exception as e:
        return [{"error": f"Chroma 검색 중 오류 발생: {str(e)}"}]
