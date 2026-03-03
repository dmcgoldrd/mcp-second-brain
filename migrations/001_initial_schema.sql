-- MCP Brain: Initial Schema
-- Requires: Supabase with pgvector extension

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Profiles table (extends Supabase auth.users)
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    display_name TEXT,
    stripe_customer_id TEXT UNIQUE,
    subscription_status TEXT DEFAULT 'free' CHECK (subscription_status IN ('free', 'active', 'canceled', 'past_due')),
    subscription_id TEXT,
    memory_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Auto-create profile on user signup
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.profiles (id, display_name)
    VALUES (NEW.id, COALESCE(NEW.raw_user_meta_data->>'full_name', NEW.email));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE OR REPLACE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION public.handle_new_user();

-- Memories table (core data model)
CREATE TABLE IF NOT EXISTS public.memories (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    embedding vector(1536),
    metadata JSONB DEFAULT '{}',
    memory_type TEXT DEFAULT 'observation' CHECK (memory_type IN ('observation', 'task', 'idea', 'reference', 'person_note', 'decision', 'preference')),
    tags TEXT[] DEFAULT '{}',
    source TEXT DEFAULT 'mcp',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),

    -- Full-text search column (auto-generated)
    fts tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_memories_user_id ON public.memories(user_id);
CREATE INDEX IF NOT EXISTS idx_memories_created_at ON public.memories(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_memory_type ON public.memories(memory_type);
CREATE INDEX IF NOT EXISTS idx_memories_tags ON public.memories USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_memories_fts ON public.memories USING GIN(fts);
CREATE INDEX IF NOT EXISTS idx_memories_metadata ON public.memories USING GIN(metadata);

-- Vector similarity index (HNSW for better recall)
CREATE INDEX IF NOT EXISTS idx_memories_embedding ON public.memories
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Row Level Security
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.memories ENABLE ROW LEVEL SECURITY;

-- Profiles: users can only read/update their own profile
CREATE POLICY "users_read_own_profile" ON public.profiles
    FOR SELECT USING (auth.uid() = id);

CREATE POLICY "users_update_own_profile" ON public.profiles
    FOR UPDATE USING (auth.uid() = id);

-- Memories: users can only CRUD their own memories
CREATE POLICY "users_read_own_memories" ON public.memories
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "users_insert_own_memories" ON public.memories
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "users_update_own_memories" ON public.memories
    FOR UPDATE USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "users_delete_own_memories" ON public.memories
    FOR DELETE USING (auth.uid() = user_id);

-- Hybrid search function (Reciprocal Ranked Fusion)
CREATE OR REPLACE FUNCTION public.hybrid_search(
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
    WHERE m.user_id = auth.uid()
        AND m.fts @@ websearch_to_tsquery(query_text)
    ORDER BY rank
    LIMIT match_count * 2
),
semantic AS (
    SELECT
        m.id,
        ROW_NUMBER() OVER (ORDER BY m.embedding <=> query_embedding) AS rank
    FROM public.memories m
    WHERE m.user_id = auth.uid()
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

-- Update memory count trigger
CREATE OR REPLACE FUNCTION public.update_memory_count()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        UPDATE public.profiles SET memory_count = memory_count + 1, updated_at = now()
        WHERE id = NEW.user_id;
    ELSIF TG_OP = 'DELETE' THEN
        UPDATE public.profiles SET memory_count = memory_count - 1, updated_at = now()
        WHERE id = OLD.user_id;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE OR REPLACE TRIGGER on_memory_change
    AFTER INSERT OR DELETE ON public.memories
    FOR EACH ROW
    EXECUTE FUNCTION public.update_memory_count();

-- Subscriptions table (Stripe webhook populates this)
CREATE TABLE IF NOT EXISTS public.subscriptions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    stripe_subscription_id TEXT UNIQUE NOT NULL,
    stripe_customer_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'canceled', 'past_due', 'trialing', 'incomplete')),
    price_id TEXT,
    current_period_start TIMESTAMPTZ,
    current_period_end TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE public.subscriptions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "users_read_own_subscription" ON public.subscriptions
    FOR SELECT USING (auth.uid() = user_id);
