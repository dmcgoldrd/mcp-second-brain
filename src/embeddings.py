"""Embedding generation via OpenAI API."""

from openai import AsyncOpenAI

from src.config import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL, OPENAI_API_KEY

_client: AsyncOpenAI | None = None


def get_openai_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    return _client


async def generate_embedding(text: str) -> list[float]:
    """Generate an embedding vector for the given text."""
    client = get_openai_client()
    response = await client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
        dimensions=EMBEDDING_DIMENSIONS,
    )
    return response.data[0].embedding


async def generate_embeddings(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for multiple texts in one API call.

    OpenAI's embeddings endpoint natively supports batch input.
    Returns embeddings in the same order as the input texts.
    """
    if not texts:
        return []

    client = get_openai_client()
    response = await client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
        dimensions=EMBEDDING_DIMENSIONS,
    )
    # OpenAI returns data sorted by index, but sort explicitly to be safe
    sorted_data = sorted(response.data, key=lambda d: d.index)
    return [d.embedding for d in sorted_data]
