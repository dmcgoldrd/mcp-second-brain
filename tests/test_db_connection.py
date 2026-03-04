"""Tests for src.db.connection — asyncpg pool with pgvector."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch


class TestGetPool:
    async def test_creates_pool_on_first_call(self):
        import src.db.connection

        src.db.connection._pool = None
        mock_pool = AsyncMock()

        with patch(
            "src.db.connection.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool
        ) as mock_create:
            pool = await src.db.connection.get_pool()
            assert pool is mock_pool
            mock_create.assert_called_once()

        src.db.connection._pool = None

    async def test_returns_cached_pool_on_second_call(self):
        import src.db.connection

        src.db.connection._pool = None
        mock_pool = AsyncMock()

        with patch(
            "src.db.connection.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool
        ) as mock_create:
            pool1 = await src.db.connection.get_pool()
            pool2 = await src.db.connection.get_pool()
            assert pool1 is pool2
            # create_pool called only once
            mock_create.assert_called_once()

        src.db.connection._pool = None

    async def test_create_pool_args(self):
        import src.db.connection

        src.db.connection._pool = None
        mock_pool = AsyncMock()

        with patch(
            "src.db.connection.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool
        ) as mock_create:
            await src.db.connection.get_pool()
            call_kwargs = mock_create.call_args
            # First positional arg is the DB URL
            assert "test" in call_kwargs.args[0]  # Our test DB URL
            assert call_kwargs.kwargs["min_size"] == 2
            assert call_kwargs.kwargs["max_size"] == 10
            assert call_kwargs.kwargs["init"] is src.db.connection._init_connection

        src.db.connection._pool = None


class TestInitConnection:
    async def test_registers_pgvector(self):
        import src.db.connection

        mock_conn = AsyncMock()

        with patch("src.db.connection.register_vector", new_callable=AsyncMock) as mock_register:
            await src.db.connection._init_connection(mock_conn)
            mock_register.assert_called_once_with(mock_conn)


class TestClosePool:
    async def test_closes_existing_pool(self):
        import src.db.connection

        mock_pool = AsyncMock()
        src.db.connection._pool = mock_pool

        await src.db.connection.close_pool()

        mock_pool.close.assert_called_once()
        assert src.db.connection._pool is None

    async def test_noop_when_no_pool(self):
        import src.db.connection

        src.db.connection._pool = None
        # Should not raise
        await src.db.connection.close_pool()
        assert src.db.connection._pool is None
