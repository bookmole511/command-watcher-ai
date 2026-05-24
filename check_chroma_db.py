# check_chroma_db.py
"""
Command Watcher AI - Chroma Vector DB 조회 테스트 스크립트
사용법: python check_chroma_db.py
"""

from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from pathlib import Path
import json
from typing import Optional

# ==================== 설정 영역 ====================
PERSIST_DIRECTORY = "./chroma_db"
COLLECTION_NAME = "command_logs"
EMBEDDING_MODEL = "BAAI/bge-m3"

# 검색 설정
TOP_K = 5                    # 검색 결과 개수
# ===================================================

def load_vectorstore():
    """Chroma DB 로드"""
    print(f"🔄 Chroma DB 로드 중... ({PERSIST_DIRECTORY})")
    embeddings = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True}
    )
    
    vectorstore = Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=PERSIST_DIRECTORY
    )
    return vectorstore

def print_db_info(vectorstore: Chroma):
    """Chroma DB 기본 정보 출력"""
    collection = vectorstore._collection
    count = collection.count()
    
    print("\n" + "="*60)
    print("📊 Chroma Vector DB 정보")
    print("="*60)
    print(f"   Collection Name : {COLLECTION_NAME}")
    print(f"   Total Documents : {count:,} 개")
    print(f"   Persist Path    : {Path(PERSIST_DIRECTORY).absolute()}")
    print("="*60)
    
    # 샘플 metadata 3개 출력
    if count > 0:
        results = collection.get(limit=3)
        print("\n📋 샘플 Metadata (최근 3개):")
        for i, meta in enumerate(results['metadatas']):
            print(f"   {i+1}. ID: {results['ids'][i]} | "
                  f"User: {meta.get('user_name')} | "
                  f"Time: {meta.get('timestamp')}")

def search_by_query(vectorstore: Chroma, query: str, top_k: int = 5):
    """자연어 검색 (similarity search)"""
    print(f"\n🔍 검색어: '{query}'")
    print(f"   Top-{top_k} 결과 출력 중...\n")
    
    results = vectorstore.similarity_search_with_score(query, k=top_k)
    
    for i, (doc, score) in enumerate(results, 1):
        meta = doc.metadata
        print(f"{i:2d}. [유사도: {score:.4f}]")
        print(f"   👤 사용자 : {meta.get('user_name')}")
        print(f"   🕒 시간    : {meta.get('timestamp')}")
        print(f"   📂 디렉토리: {meta.get('current_dir')}")
        print(f"   💻 명령어  : {doc.page_content[:120]}...")
        print(f"   🔑 ID      : {meta.get('id')}")
        print("-" * 50)

def main() -> None:
    if not Path(PERSIST_DIRECTORY).exists():
        print("❌ Chroma DB 폴더를 찾을 수 없습니다.")
        print(f"   먼저 python build_vector_db.py 를 실행해주세요.")
        return
    
    vectorstore = load_vectorstore()
    print_db_info(vectorstore)
    
    # 간단한 인터랙티브 검색
    print("\n💡 자연어로 검색해보세요! (종료하려면 빈 줄 입력)")
    while True:
        query = input("\n🔎 검색어 > ").strip()
        if not query:
            print("👋 종료합니다.")
            break
        search_by_query(vectorstore, query, TOP_K)

if __name__ == "__main__":
    main()