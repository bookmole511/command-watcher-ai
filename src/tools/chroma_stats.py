"""Chroma metadata aggregation tools."""

from typing import Any, Dict

import chromadb
from langchain_core.tools import tool

from src.config import CHROMA_COLLECTION_NAME, CHROMA_PERSIST_DIR


@tool
def chroma_user_summary(include_users: bool = True) -> Dict[str, Any]:
    """
    Return distinct user statistics from Chroma metadata.

    Args:
        include_users: Whether to include the sorted distinct user list.

    Returns:
        Chroma collection document count and distinct user count.
    """
    try:
        client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
        collection = client.get_collection(CHROMA_COLLECTION_NAME)
        result = collection.get(include=["metadatas"])

        users = sorted(
            {
                metadata.get("user_name")
                for metadata in result.get("metadatas", [])
                if metadata and metadata.get("user_name")
            }
        )

        payload: Dict[str, Any] = {
            "success": True,
            "collection": CHROMA_COLLECTION_NAME,
            "persist_directory": CHROMA_PERSIST_DIR,
            "document_count": collection.count(),
            "user_count": len(users),
        }
        if include_users:
            payload["users"] = users
        return payload

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "Chroma metadata aggregation failed. Check the persist directory and collection name.",
        }
