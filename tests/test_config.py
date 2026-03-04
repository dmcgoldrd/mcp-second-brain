"""Tests for src.config — environment variable loading."""

from __future__ import annotations

import importlib
import os
from unittest.mock import patch

import pytest


def _reload_config(monkeypatch, overrides: dict | None = None):
    """Set env vars and reimport src.config to pick them up.

    Patches dotenv.load_dotenv to prevent the real .env file from
    polluting the test environment during module reload.
    """
    base = {
        "SUPABASE_URL": "https://test.supabase.co",
        "SUPABASE_ANON_KEY": "test-anon-key",
        "SUPABASE_SERVICE_ROLE_KEY": "test-service-role-key",
        "SUPABASE_DB_URL": "postgresql://test:test@localhost:5432/test",
        "OPENAI_API_KEY": "test-openai-key",
    }
    if overrides:
        base.update(overrides)

    # Clear ALL config-related env vars so defaults are tested
    for key in list(os.environ.keys()):
        if (
            key.startswith("SUPABASE_")
            or key.startswith("OPENAI_")
            or key
            in (
                "EMBEDDING_MODEL",
                "EMBEDDING_DIMENSIONS",
                "HOST",
                "PORT",
                "ENVIRONMENT",
                "FREE_MEMORY_LIMIT",
                "FREE_RETRIEVAL_LIMIT",
                "PAID_MEMORY_LIMIT",
            )
        ):
            monkeypatch.delenv(key, raising=False)

    for key, val in base.items():
        monkeypatch.setenv(key, val)

    import src.config

    with patch("dotenv.load_dotenv"):
        return importlib.reload(src.config)


# ---- Required env vars ----


def test_required_vars_loaded(monkeypatch):
    cfg = _reload_config(monkeypatch)
    assert cfg.SUPABASE_URL == "https://test.supabase.co"
    assert cfg.SUPABASE_ANON_KEY == "test-anon-key"
    assert cfg.SUPABASE_SERVICE_ROLE_KEY == "test-service-role-key"
    assert cfg.SUPABASE_DB_URL == "postgresql://test:test@localhost:5432/test"
    assert cfg.OPENAI_API_KEY == "test-openai-key"


def test_missing_required_var_raises(monkeypatch):
    """If a required env var is missing, import should raise KeyError."""
    for key in list(os.environ.keys()):
        if key.startswith("SUPABASE_") or key.startswith("OPENAI_"):
            monkeypatch.delenv(key, raising=False)

    import src.config

    with (
        patch("dotenv.load_dotenv"),
        pytest.raises(KeyError),
    ):
        importlib.reload(src.config)


# ---- Defaults ----


def test_defaults(monkeypatch):
    cfg = _reload_config(monkeypatch)
    assert cfg.EMBEDDING_MODEL == "text-embedding-3-small"
    assert cfg.EMBEDDING_DIMENSIONS == 1536
    assert cfg.HOST == "0.0.0.0"
    assert cfg.PORT == 8080
    assert cfg.ENVIRONMENT == "development"
    assert cfg.FREE_MEMORY_LIMIT == 1000
    assert cfg.FREE_RETRIEVAL_LIMIT == 500
    assert cfg.PAID_MEMORY_LIMIT == 50000
    assert cfg.SUPABASE_JWKS_URL == "https://test.supabase.co/auth/v1/.well-known/jwks.json"


# ---- Custom overrides ----


def test_custom_overrides(monkeypatch):
    cfg = _reload_config(
        monkeypatch,
        overrides={
            "EMBEDDING_MODEL": "text-embedding-3-large",
            "EMBEDDING_DIMENSIONS": "3072",
            "HOST": "127.0.0.1",
            "PORT": "9090",
            "ENVIRONMENT": "production",
            "FREE_MEMORY_LIMIT": "2000",
            "FREE_RETRIEVAL_LIMIT": "1000",
            "PAID_MEMORY_LIMIT": "100000",
            "SUPABASE_JWKS_URL": "https://custom.jwks.url/jwks",
        },
    )
    assert cfg.EMBEDDING_MODEL == "text-embedding-3-large"
    assert cfg.EMBEDDING_DIMENSIONS == 3072
    assert cfg.HOST == "127.0.0.1"
    assert cfg.PORT == 9090
    assert cfg.ENVIRONMENT == "production"
    assert cfg.FREE_MEMORY_LIMIT == 2000
    assert cfg.FREE_RETRIEVAL_LIMIT == 1000
    assert cfg.PAID_MEMORY_LIMIT == 100000
    assert cfg.SUPABASE_JWKS_URL == "https://custom.jwks.url/jwks"


# ---- JWKS URL derived from SUPABASE_URL ----


def test_jwks_url_derived_from_supabase_url(monkeypatch):
    """SUPABASE_JWKS_URL defaults to SUPABASE_URL + /auth/v1/.well-known/jwks.json."""
    cfg = _reload_config(
        monkeypatch,
        overrides={"SUPABASE_URL": "https://custom-project.supabase.co"},
    )
    assert (
        cfg.SUPABASE_JWKS_URL == "https://custom-project.supabase.co/auth/v1/.well-known/jwks.json"
    )
