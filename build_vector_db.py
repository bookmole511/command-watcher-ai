"""Build the Chroma vector database from MySQL command history."""

from pathlib import Path
from typing import Optional
import time

import pandas as pd
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from sqlalchemy import create_engine

from src.config import (
    CHROMA_COLLECTION_NAME,
    CHROMA_PERSIST_DIR,
    DB_NAME,
    DB_URL,
    EMBEDDING_MODEL,
    MAX_ROWS_FOR_ANALYSIS,
)


PERSIST_DIRECTORY = CHROMA_PERSIST_DIR
COLLECTION_NAME = CHROMA_COLLECTION_NAME
MAX_ROWS = MAX_ROWS_FOR_ANALYSIS


def get_mysql_engine(db_url: str):
    """Create a SQLAlchemy engine."""
    return create_engine(db_url)


def load_data_from_mysql(engine, max_rows: Optional[int] = None) -> pd.DataFrame:
    """Load command_history rows from MySQL."""
    query = f"""
        SELECT
            id, user_name, command, timestamp, current_dir,
            client_ip, server_ip, exit_code, session_id, created_at
        FROM {DB_NAME}.command_history
        ORDER BY timestamp DESC
    """
    if max_rows:
        query += f" LIMIT {int(max_rows)}"

    print(f"Loading command history from MySQL (max rows: {max_rows or 'all'})")
    df = pd.read_sql(query, engine)
    print(f"Loaded {len(df)} rows")
    return df


def create_documents(df: pd.DataFrame):
    """Convert command history rows into Chroma documents and metadata."""
    documents = []
    metadatas = []
    ids = []

    for _, row in df.iterrows():
        doc_text = (
            f"user: {row['user_name']} | "
            f"command: {row['command']} | "
            f"time: {row['timestamp']} | "
            f"dir: {row['current_dir']} | "
            f"client_ip: {row['client_ip']} | "
            f"server_ip: {row['server_ip']} | "
            f"exit_code: {row['exit_code']} | "
            f"session: {row['session_id']}"
        )

        documents.append(doc_text)
        metadatas.append(
            {
                "id": int(row["id"]),
                "user_name": row["user_name"],
                "timestamp": str(row["timestamp"]),
                "current_dir": row["current_dir"],
                "client_ip": row["client_ip"],
                "server_ip": row["server_ip"],
                "exit_code": int(row["exit_code"]),
                "session_id": row["session_id"],
            }
        )
        ids.append(f"log_{row['id']}")

    return documents, metadatas, ids


def main() -> None:
    start_time = time.time()
    print("Chroma vector DB build started")
    print(f"   Embedding model : {EMBEDDING_MODEL}")
    print(f"   Persist path    : {PERSIST_DIRECTORY}")
    print(f"   Collection      : {COLLECTION_NAME}")
    print("-" * 70)

    try:
        engine = get_mysql_engine(DB_URL)
        df = load_data_from_mysql(engine, max_rows=MAX_ROWS)

        if len(df) == 0:
            print("No data found. Run import_csv.py first.")
            return

        documents, metadatas, ids = create_documents(df)

        print(f"Loading embedding model: {EMBEDDING_MODEL}")
        embeddings = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )

        print("Building Chroma vector DB")
        vectorstore = Chroma.from_texts(
            texts=documents,
            embedding=embeddings,
            metadatas=metadatas,
            ids=ids,
            collection_name=COLLECTION_NAME,
            persist_directory=PERSIST_DIRECTORY,
        )
        vectorstore.persist()

        elapsed = time.time() - start_time
        print("\nChroma vector DB build completed")
        print(f"   Documents : {len(documents)}")
        print(f"   Elapsed   : {elapsed:.1f}s")
        print(f"   Path      : {Path(PERSIST_DIRECTORY).absolute()}")

    except Exception as e:
        print(f"\nVector DB build failed: {e}")
        print("Check MySQL connection, credentials, and embedding model availability.")


if __name__ == "__main__":
    main()
