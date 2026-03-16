"""Tests for src.embeddings.generate_embeddings — batch embedding generation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from tests.conftest import FAKE_EMBEDDING

# ===== generate_embeddings =====


class TestGenerateEmbeddings:
    async def test_generate_embeddings_returns_list(self):
        from src.embeddings import generate_embeddings

        emb_a = MagicMock()
        emb_a.embedding = FAKE_EMBEDDING
        emb_a.index = 0

        emb_b = MagicMock()
        emb_b.embedding = [0.2] * 1536
        emb_b.index = 1

        response = MagicMock()
        response.data = [emb_a, emb_b]

        mock_client = AsyncMock()
        mock_client.embeddings.create = AsyncMock(return_value=response)

        with patch("src.embeddings.get_openai_client", return_value=mock_client):
            result = await generate_embeddings(["text one", "text two"])

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0] == FAKE_EMBEDDING
        assert result[1] == [0.2] * 1536
        # Called once with both texts in a single batch
        mock_client.embeddings.create.assert_called_once()
        call_kwargs = mock_client.embeddings.create.call_args.kwargs
        assert call_kwargs["input"] == ["text one", "text two"]

    async def test_generate_embeddings_empty_input(self):
        from src.embeddings import generate_embeddings

        # Empty input should return empty list without calling the API
        mock_client = AsyncMock()

        with patch("src.embeddings.get_openai_client", return_value=mock_client):
            result = await generate_embeddings([])

        assert result == []
        mock_client.embeddings.create.assert_not_called()

    async def test_generate_embeddings_preserves_order(self):
        """OpenAI may return embeddings out of order — we sort by index."""
        from src.embeddings import generate_embeddings

        emb_0 = MagicMock()
        emb_0.embedding = [0.1] * 1536
        emb_0.index = 0

        emb_1 = MagicMock()
        emb_1.embedding = [0.2] * 1536
        emb_1.index = 1

        emb_2 = MagicMock()
        emb_2.embedding = [0.3] * 1536
        emb_2.index = 2

        # Return out of order to verify sorting
        response = MagicMock()
        response.data = [emb_2, emb_0, emb_1]

        mock_client = AsyncMock()
        mock_client.embeddings.create = AsyncMock(return_value=response)

        with patch("src.embeddings.get_openai_client", return_value=mock_client):
            result = await generate_embeddings(["a", "b", "c"])

        assert len(result) == 3
        # Should be sorted by index, not by the order returned
        assert result[0] == [0.1] * 1536
        assert result[1] == [0.2] * 1536
        assert result[2] == [0.3] * 1536
