# Database

MCP Brain uses Supabase Postgres with pgvector for vector similarity search. The server connects directly via asyncpg (bypassing PostgREST) with a connection pool.

## Connection Pool

**File:** `src/db/connection.py`

```python
pool = await asyncpg.create_pool(
    SUPABASE_DB_URL,
    min_size=2,
    max_size=10,
    init=_init_connection,  # registers pgvector codec per connection
)
```

- **Lazy initialization:** Pool is created on first database call, not at server startup
- **pgvector codec:** `register_vector(conn)` is called on each new connection to handle `vector` type serialization
- **Cleanup:** `close_pool()` closes the pool and resets the global reference

## Schema

### `profiles`

Stores user profile data. Created automatically by the `handle_new_user` trigger when a user signs up.

```sql
CREATE TABLE public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    display_name TEXT,
    stripe_customer_id TEXT UNIQUE,
    subscription_status TEXT DEFAULT 'free'
        CHECK (subscription_status IN ('free', 'active', 'canceled', 'past_due')),
    subscription_id TEXT,
    memory_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
```

### `banks`

Memory banks allow users to organize memories into separate collections.

```sql
CREATE TABLE public.banks (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    is_default BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, slug)
);
```

A default bank is created for each user by the `handle_new_user` trigger.

### `memories`

The core table. Stores memory content, embeddings, metadata, and classification.

```sql
CREATE TABLE public.memories (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    bank_id UUID NOT NULL REFERENCES banks(id),
    content TEXT NOT NULL,
    embedding vector(1536),
    metadata JSONB DEFAULT '{}',
    memory_type TEXT DEFAULT 'observation'
        CHECK (memory_type IN (
            'observation', 'task', 'idea', 'reference',
            'person_note', 'decision', 'preference'
        )),
    tags TEXT[] DEFAULT '{}',
    source TEXT DEFAULT 'mcp',
    fts tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
```

### `subscriptions`

Stripe subscription data, populated by the `stripe-webhook` Edge Function.

```sql
CREATE TABLE public.subscriptions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    stripe_subscription_id TEXT UNIQUE NOT NULL,
    stripe_customer_id TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK (status IN ('active', 'canceled', 'past_due', 'trialing', 'incomplete')),
    price_id TEXT,
    current_period_start TIMESTAMPTZ,
    current_period_end TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
```

## Indexes

### `memories` Table

| Index | Type | Column(s) | Purpose |
|-------|------|-----------|---------|
| `idx_memories_user_id` | B-tree | `user_id` | User-scoped queries |
| `idx_memories_created_at` | B-tree | `created_at DESC` | Chronological listing |
| `idx_memories_memory_type` | B-tree | `memory_type` | Type filtering |
| `idx_memories_tags` | GIN | `tags` | Tag-based queries |
| `idx_memories_fts` | GIN | `fts` | Full-text search |
| `idx_memories_metadata` | GIN | `metadata` | JSONB metadata queries |
| `idx_memories_embedding` | HNSW | `embedding vector_cosine_ops` | Vector similarity search (m=16, ef_construction=64) |

## Hybrid Search Function

The `hybrid_search()` PostgreSQL function combines semantic (vector) and full-text search using Reciprocal Ranked Fusion (RRF).

```sql
CREATE OR REPLACE FUNCTION public.hybrid_search(
    p_user_id UUID,
    p_bank_id UUID,
    query_text TEXT,
    query_embedding vector(1536),
    match_count INTEGER DEFAULT 10,
    full_text_weight FLOAT DEFAULT 1.0,
    semantic_weight FLOAT DEFAULT 1.0,
    rrf_k INTEGER DEFAULT 60
)
RETURNS TABLE (
    id UUID, content TEXT, metadata JSONB, memory_type TEXT,
    tags TEXT[], source TEXT, created_at TIMESTAMPTZ, score FLOAT
)
LANGUAGE sql STABLE
AS $$
WITH full_text AS (
    SELECT m.id,
           ROW_NUMBER() OVER (
               ORDER BY ts_rank_cd(m.fts, websearch_to_tsquery(query_text)) DESC
           ) AS rank
    FROM public.memories m
    WHERE m.user_id = p_user_id
      AND m.fts @@ websearch_to_tsquery(query_text)
    LIMIT match_count * 2
),
semantic AS (
    SELECT m.id,
           ROW_NUMBER() OVER (ORDER BY m.embedding <=> query_embedding) AS rank
    FROM public.memories m
    WHERE m.user_id = p_user_id
      AND m.embedding IS NOT NULL
    ORDER BY m.embedding <=> query_embedding
    LIMIT match_count * 2
)
SELECT m.id, m.content, m.metadata, m.memory_type, m.tags, m.source, m.created_at,
    COALESCE((full_text_weight / (rrf_k + ft.rank)), 0.0)
    + COALESCE((semantic_weight / (rrf_k + s.rank)), 0.0) AS score
FROM public.memories m
LEFT JOIN full_text ft ON m.id = ft.id
LEFT JOIN semantic s ON m.id = s.id
WHERE ft.id IS NOT NULL OR s.id IS NOT NULL
ORDER BY score DESC
LIMIT match_count;
$$;
```

### How RRF Works

RRF (Reciprocal Ranked Fusion) combines two ranked lists into a single score:

```
score = (ft_weight / (k + ft_rank)) + (sem_weight / (k + sem_rank))
```

- `k = 60` (default) smooths rank differences — a document ranked #1 in full-text and #10 in semantic gets a combined score, not just the best single score
- `full_text_weight` and `semantic_weight` (both default 1.0) control the relative importance
- Documents appearing in only one list get 0 for the missing component

## Triggers

### `handle_new_user`

Fires `AFTER INSERT ON auth.users`. Creates a profile and default bank for every new user.

```sql
CREATE OR REPLACE FUNCTION public.handle_new_user() RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.profiles (id, display_name)
    VALUES (NEW.id, COALESCE(NEW.raw_user_meta_data->>'full_name', NEW.email));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
```

### `update_memory_count`

Fires `AFTER INSERT OR DELETE ON memories`. Keeps `profiles.memory_count` in sync.

```sql
CREATE OR REPLACE FUNCTION public.update_memory_count() RETURNS TRIGGER AS $$
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
```

## Row-Level Security (RLS)

All 4 tables have `ENABLE ROW LEVEL SECURITY`. RLS policies use `auth.uid()` and are enforced for PostgREST/Supabase client access (the frontend uses PostgREST).

The backend server connects via asyncpg with the database connection string, which **bypasses RLS**. Application-layer scoping (`WHERE user_id = ? AND bank_id = ?`) provides the isolation boundary for backend operations.

## Database Access Layer

### `src/db/memories.py`

| Function | Description | Key SQL |
|----------|-------------|---------|
| `create_memory(user_id, bank_id, content, embedding, ...)` | Insert memory with embedding | `INSERT INTO memories ... RETURNING ...` |
| `search_memories(user_id, bank_id, query_embedding, query_text, limit)` | Hybrid or pure semantic search | `SELECT FROM hybrid_search(...)` or cosine `<=>` |
| `list_memories(user_id, bank_id, limit, offset, memory_type)` | Paginated listing | `SELECT ... ORDER BY created_at DESC LIMIT ? OFFSET ?` |
| `delete_memory(user_id, bank_id, memory_id)` | Delete by ID | `DELETE FROM memories WHERE id = ? AND user_id = ? AND bank_id = ?` |
| `get_memory_stats(user_id, bank_id)` | Aggregate stats | `COUNT(*)`, `MIN/MAX(created_at)`, `jsonb_object_agg` |

All functions validate UUIDs before querying and return empty results on invalid format.

### `src/db/banks.py`

| Function | Description |
|----------|-------------|
| `get_user_banks(user_id)` | All banks for user, default first |
| `get_bank_by_slug(user_id, slug)` | Single bank by slug |
| `get_default_bank(user_id)` | Bank with `is_default = true` |
| `create_bank(user_id, name, slug)` | Insert new bank (`is_default = false`) |

### `src/db/profiles.py`

| Function | Description |
|----------|-------------|
| `get_profile(user_id)` | Full profile including subscription status |
| `get_memory_count(user_id)` | Current memory count (0 if no profile) |
| `is_subscription_active(user_id)` | `True` only if `subscription_status == "active"` |

## Migrations

| # | File | Description |
|---|------|-------------|
| 001 | `initial_schema` | profiles, memories, subscriptions tables + indexes + triggers |
| 002 | `fix_hybrid_search` | Updated hybrid_search to accept `p_user_id` and `p_bank_id`, added banks table, added `bank_id` FK to memories |
