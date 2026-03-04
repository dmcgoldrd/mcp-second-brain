"""Tests for src.embeddings — OpenAI embedding generation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from tests.conftest import FAKE_EMBEDDING


class TestGenerateEmbedding:
    async def test_returns_embedding_list(self, mock_openai_embedding):
        from src.embeddings import generate_embedding

        result = await generate_embedding("hello world")
        assert result == FAKE_EMBEDDING
        assert isinstance(result, list)
        assert len(result) == 1536

    async def test_calls_openai_with_correct_params(self, mock_openai_embedding):
        from src.embeddings import generate_embedding

        await generate_embedding("test text")
        mock_openai_embedding.embeddings.create.assert_called_once()
        call_kwargs = mock_openai_embedding.embeddings.create.call_args
        assert call_kwargs.kwargs["input"] == "test text"

    async def test_uses_config_model_and_dimensions(self, mock_openai_embedding):
        from src.embeddings import generate_embedding

        await generate_embedding("anything")
        call_kwargs = mock_openai_embedding.embeddings.create.call_args
        # Should use the configured model and dimensions from src.config
        assert "model" in call_kwargs.kwargs
        assert "dimensions" in call_kwargs.kwargs


class TestGetClient:
    def test_singleton_pattern(self):
        """_get_client should return the same client on subsequent calls."""
        import src.embeddings

        # Reset singleton
        src.embeddings._client = None

        with patch("src.embeddings.AsyncOpenAI") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance

            client1 = src.embeddings._get_client()
            client2 = src.embeddings._get_client()

            assert client1 is client2
            # Constructor called only once
            mock_cls.assert_called_once()

        # Reset
        src.embeddings._client = None

    def test_creates_client_with_api_key(self):
        import src.embeddings

        src.embeddings._client = None

        with patch("src.embeddings.AsyncOpenAI") as mock_cls:
            src.embeddings._get_client()
            mock_cls.assert_called_once()
            call_kwargs = mock_cls.call_args
            assert "api_key" in call_kwargs.kwargs

        src.embeddings._client = None
