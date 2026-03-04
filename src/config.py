"""Configuration loaded from environment variables."""

import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("mcp-brain")

# Supabase
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_DB_URL = os.environ["SUPABASE_DB_URL"]
SUPABASE_JWKS_URL = os.environ.get(
    "SUPABASE_JWKS_URL",
    f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json",
)

# F-13: Warn if DB connection URL lacks SSL
if "sslmode" not in SUPABASE_DB_URL:
    logger.warning("SUPABASE_DB_URL missing sslmode — database connections may be unencrypted")

# OpenAI
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIMENSIONS = int(os.environ.get("EMBEDDING_DIMENSIONS", "1536"))

# Server
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8080"))
ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8080")

# Limits
FREE_MEMORY_LIMIT = int(os.environ.get("FREE_MEMORY_LIMIT", "1000"))
FREE_RETRIEVAL_LIMIT = int(os.environ.get("FREE_RETRIEVAL_LIMIT", "500"))
PAID_MEMORY_LIMIT = int(os.environ.get("PAID_MEMORY_LIMIT", "50000"))
MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", "50000"))  # ~50KB
MAX_METADATA_LENGTH = int(os.environ.get("MAX_METADATA_LENGTH", "10000"))
MAX_BANKS_FREE = int(os.environ.get("MAX_BANKS_FREE", "10"))
MAX_BANKS_PAID = int(os.environ.get("MAX_BANKS_PAID", "50"))

# Input validation
VALID_MEMORY_TYPES = {
    "observation",
    "task",
    "idea",
    "reference",
    "person_note",
    "decision",
    "preference",
}
VALID_SOURCES = {"mcp", "slack", "manual", "import"}
MAX_TAGS = 20
MAX_TAG_LENGTH = 100
MAX_BANK_NAME_LENGTH = 100
MAX_BANK_SLUG_LENGTH = 50
MAX_QUERY_LENGTH = 10000  # ~10KB search query limit
