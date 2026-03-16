-- GIN index on memory_entities.memory_ids for the recursive CTE in
-- get_related_entities (array overlap operator &&).
-- Without this, each recursive hop does a sequential scan.

CREATE INDEX IF NOT EXISTS idx_entities_memory_ids
    ON public.memory_entities USING GIN(memory_ids);
