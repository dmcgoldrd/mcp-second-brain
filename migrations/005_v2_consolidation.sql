-- MCP Brain v2: Consolidation infrastructure, access tracking, entity extraction
-- Run after 004_bank_limit_trigger.sql

-- New columns on memories for access tracking and consolidation
ALTER TABLE public.memories ADD COLUMN IF NOT EXISTS access_count INTEGER DEFAULT 0;
ALTER TABLE public.memories ADD COLUMN IF NOT EXISTS last_accessed_at TIMESTAMPTZ;
ALTER TABLE public.memories ADD COLUMN IF NOT EXISTS importance_score FLOAT DEFAULT 0.0;
ALTER TABLE public.memories ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;
ALTER TABLE public.memories ADD COLUMN IF NOT EXISTS archived_reason TEXT;
ALTER TABLE public.memories ADD COLUMN IF NOT EXISTS superseded_by UUID REFERENCES public.memories(id);
ALTER TABLE public.memories ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1;

-- Index for filtering archived memories (partial index for efficiency)
CREATE INDEX IF NOT EXISTS idx_memories_archived ON public.memories(archived_at)
    WHERE archived_at IS NOT NULL;

-- Index for consolidation queries (importance scoring)
CREATE INDEX IF NOT EXISTS idx_memories_importance ON public.memories(importance_score DESC)
    WHERE archived_at IS NULL;

-- Consolidation log table
CREATE TABLE IF NOT EXISTS public.consolidation_log (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    bank_id UUID NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('merge', 'archive', 'update_score', 'extract_entity', 'resolve_conflict')),
    memory_ids UUID[] NOT NULL,
    details JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_consolidation_log_user ON public.consolidation_log(user_id, created_at DESC);

ALTER TABLE public.consolidation_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY "users_read_own_consolidation_log" ON public.consolidation_log
    FOR SELECT USING (auth.uid() = user_id);

-- Memory entities table (Postgres-native graph alternative)
CREATE TABLE IF NOT EXISTS public.memory_entities (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    bank_id UUID NOT NULL,
    entity_name TEXT NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('person', 'organization', 'place', 'project', 'topic')),
    facts JSONB DEFAULT '[]',
    memory_ids UUID[] DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, bank_id, entity_name, entity_type)
);

CREATE INDEX IF NOT EXISTS idx_entities_user_bank ON public.memory_entities(user_id, bank_id);
CREATE INDEX IF NOT EXISTS idx_entities_name ON public.memory_entities USING GIN(to_tsvector('english', entity_name));

ALTER TABLE public.memory_entities ENABLE ROW LEVEL SECURITY;

CREATE POLICY "users_read_own_entities" ON public.memory_entities
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "users_insert_own_entities" ON public.memory_entities
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "users_update_own_entities" ON public.memory_entities
    FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "users_delete_own_entities" ON public.memory_entities
    FOR DELETE USING (auth.uid() = user_id);

-- Add last_consolidation_at to profiles
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS last_consolidation_at TIMESTAMPTZ;
