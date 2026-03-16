-- Composite partial index for the most common consolidation query pattern:
-- filtering by (user_id, bank_id) WHERE archived_at IS NULL.
-- Without this, consolidation phases do sequential scans filtered by user_id index.

CREATE INDEX IF NOT EXISTS idx_memories_user_bank_active
    ON public.memories(user_id, bank_id)
    WHERE archived_at IS NULL;
