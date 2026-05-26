# src/config.py
"""
Command Watcher AI - central configuration.

Keep this file commit-safe. Put local secrets in `.env` or server environment
variables instead of hardcoding them here.
"""

from pathlib import Path
import os
import urllib.parse


PROJECT_ROOT = Path(__file__).parent.parent.absolute()


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        os.environ.setdefault(key, value)


_load_env_file(PROJECT_ROOT / ".env")


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return int(value)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return float(value)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _default_llm_threads() -> int:
    cpu_count = os.cpu_count() or 4
    return max(1, min(cpu_count, 4))


# ==================== LLM settings ====================
# CPU-only default: smaller than 8B-class models and easier to run without GPU.
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:3b")
LLM_TEMPERATURE = _env_float("LLM_TEMPERATURE", 0.3)
LLM_NUM_CTX = _env_int("LLM_NUM_CTX", 4096)
LLM_NUM_THREAD = _env_int("LLM_NUM_THREAD", _default_llm_threads())
LLM_NUM_PREDICT = _env_int("LLM_NUM_PREDICT", 512)

# ==================== Database settings ====================
DB_USER = os.getenv("DB_USER", "cmd_admin")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = _env_int("DB_PORT", 3306)
DB_NAME = os.getenv("DB_NAME", "cmd_watcher")

DB_URL = os.getenv("DB_URL") or (
    f"mysql+pymysql://{DB_USER}:"
    f"{urllib.parse.quote_plus(DB_PASSWORD)}"
    f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# ==================== Chroma Vector DB settings ====================
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./chroma_db")
CHROMA_COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "command_logs")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")

# ==================== Project settings ====================
DEBUG = _env_bool("DEBUG", True)
MAX_ROWS_FOR_ANALYSIS = _env_int("MAX_ROWS_FOR_ANALYSIS", 3000)

# ==================== FastAPI settings ====================
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = _env_int("API_PORT", 8000)
API_RELOAD = _env_bool("API_RELOAD", True)
