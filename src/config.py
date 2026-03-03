"""Configuration loaded from environment variables."""

import os

from dotenv import load_dotenv

load_dotenv()


# Supabase
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
SUPABASE_DB_URL = os.environ["SUPABASE_DB_URL"]
SUPABASE_JWKS_URL = os.environ.get(
    "SUPABASE_JWKS_URL",
    f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json",
)

# OpenAI
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIMENSIONS = int(os.environ.get("EMBEDDING_DIMENSIONS", "1536"))

# Server
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8080"))
ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")

# Limits
FREE_MEMORY_LIMIT = int(os.environ.get("FREE_MEMORY_LIMIT", "1000"))
FREE_RETRIEVAL_LIMIT = int(os.environ.get("FREE_RETRIEVAL_LIMIT", "500"))
PAID_MEMORY_LIMIT = int(os.environ.get("PAID_MEMORY_LIMIT", "50000"))
