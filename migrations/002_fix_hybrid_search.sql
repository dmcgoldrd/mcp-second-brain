-- Fix hybrid_search() to accept explicit user_id instead of auth.uid()
-- auth.uid() returns NULL when called via asyncpg (not PostgREST),
-- so we pass the validated user_id from the application layer.

CREATE OR REPLACE FUNCTION public.hybrid_search(
    p_user_id UUID,
    query_text TEXT,
    query_embedding vector(1536),
    match_count INTEGER DEFAULT 10,
    full_text_weight FLOAT DEFAULT 1.0,
    semantic_weight FLOAT DEFAULT 1.0,
    rrf_k INTEGER DEFAULT 60
)
RETURNS TABLE (
    id UUID,
    content TEXT,
    metadata JSONB,
    memory_type TEXT,
    tags TEXT[],
    source TEXT,
    created_at TIMESTAMPTZ,
    score FLOAT
)
LANGUAGE sql STABLE
AS $$
WITH full_text AS (
    SELECT
        m.id,
        ROW_NUMBER() OVER (ORDER BY ts_rank_cd(m.fts, websearch_to_tsquery(query_text)) DESC) AS rank
    FROM public.memories m
    WHERE m.user_id = p_user_id
        AND m.fts @@ websearch_to_tsquery(query_text)
    ORDER BY rank
    LIMIT match_count * 2
),
semantic AS (
    SELECT
        m.id,
        ROW_NUMBER() OVER (ORDER BY m.embedding <=> query_embedding) AS rank
    FROM public.memories m
    WHERE m.user_id = p_user_id
        AND m.embedding IS NOT NULL
    ORDER BY m.embedding <=> query_embedding
    LIMIT match_count * 2
)
SELECT
    m.id,
    m.content,
    m.metadata,
    m.memory_type,
    m.tags,
    m.source,
    m.created_at,
    COALESCE(
        (full_text_weight / (rrf_k + ft.rank)),
        0.0
    ) + COALESCE(
        (semantic_weight / (rrf_k + s.rank)),
        0.0
    ) AS score
FROM public.memories m
LEFT JOIN full_text ft ON m.id = ft.id
LEFT JOIN semantic s ON m.id = s.id
WHERE ft.id IS NOT NULL OR s.id IS NOT NULL
ORDER BY score DESC
LIMIT match_count;
$$;
