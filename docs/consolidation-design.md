# Memory Consolidation Design

First-principles analysis of nightly memory consolidation, derived from human cognition analogues.

## Human Memory → Software Mapping

| Human Process | What Actually Happens | Software Analogue |
|---|---|---|
| Hippocampal replay | Short-term memories replayed during sleep | Reprocess recent memories, compute importance scores |
| Myelination | Frequently-accessed pathways get faster | Frequently-searched memories get boosted relevance |
| Forgetting curve | Unused memories decay exponentially | Time-decayed importance scoring |
| Reconsolidation | Recalled memories become updatable | Retrieved memories can be merged with new context |
| Retroactive interference | New similar memories overwrite old | Contradictory facts: newer supersedes older |
| Schema integration | Episodic → semantic knowledge | Entity extraction: specific memories → entity profiles |
| Emotional tagging | Important memories prioritized | User-marked or high-engagement memories get priority |

## Two-Tier Architecture

### Tier 1: On-Write Conflict Detection (every `create_memory` call)

Before inserting a new memory:
1. Search for top-5 similar existing memories (embedding cosine > 0.85)
2. If high-similarity match found, classify:
   - **Fact update** ("wife is Maria" → "wife is Margaret"): Replace old, preserve in history
   - **Additive** ("Alice at Acme" + "Alice's email"): Enrich existing memory metadata
   - **Related but different**: Keep both, no action
3. Return conflict info to MCP client so it can help resolve
4. Insert (or update) memory

### Tier 2: Nightly Batch Consolidation (cron, per-user)

**Scope**: Only memories created/accessed since last consolidation run.

**Operations**:
1. **Importance scoring**:
   ```
   score = recency_weight × (1/days_old)
         + access_weight × access_count
         + entity_weight × entity_connection_count
   ```
2. **Near-duplicate detection**: Pairs with cosine similarity > 0.90 → merge candidates
3. **Contradiction resolution**: Pairs with similarity 0.80-0.90 + same entities → LLM check
4. **Entity graph update**: Extract and update entity relationships
5. **Decay**: Memories with low score + age > 90 days → mark "archived"

## Cost Analysis (5,000 memories, active user)

| Operation | Count | Cost |
|-----------|-------|------|
| Embedding comparisons | 0 (reuse existing vectors) | $0.00 |
| Similarity queries | ~5 SQL queries | $0.00 (Postgres) |
| LLM conflict checks | ~20-50 ambiguous pairs | $0.01-0.05 (Haiku) |
| **Total per user/night** | | **~$0.01-0.05** |
| **1,000 users/month** | | **~$300-1,500** |

## Key Design Decisions

1. **Never re-embed** — existing vectors are still valid. Only embed merged memories.
2. **Pre-filter with embeddings** — cosine similarity reduces LLM calls by 99%+.
3. **Let the MCP client help** — the AI creating the memory has conversation context. Return similar memories so the client can resolve conflicts for free.
4. **Soft delete everything** — `archived_at` + `archived_reason` columns. Never hard-delete.
5. **Incremental processing** — only memories touched since last run. Scales to 100K+ memories.
6. **Conservative thresholds** — high similarity required for auto-merge. Ambiguous cases escalate to LLM.

## Database Changes Required

### New columns on `memories`:
- `access_count INTEGER DEFAULT 0` — incremented on search result return
- `last_accessed_at TIMESTAMPTZ` — updated when memory appears in search results
- `importance_score FLOAT DEFAULT 0.0` — computed during consolidation
- `archived_at TIMESTAMPTZ` — soft delete for consolidation
- `archived_reason TEXT` — why it was archived (duplicate, stale, merged)
- `superseded_by UUID` — points to the memory that replaced this one
- `version INTEGER DEFAULT 1` — incremented on update/merge

### New table `consolidation_log`:
- `id UUID PRIMARY KEY`
- `user_id UUID`
- `bank_id UUID`
- `action TEXT` — merge, archive, update_score, extract_entity
- `memory_ids UUID[]` — affected memories
- `details JSONB` — action-specific details
- `created_at TIMESTAMPTZ`

### New table `memory_entities`:
- `id UUID PRIMARY KEY`
- `user_id UUID`
- `bank_id UUID`
- `entity_name TEXT`
- `entity_type TEXT` — person, organization, place, project, topic
- `memory_ids UUID[]` — memories referencing this entity
- `metadata JSONB` — accumulated facts about this entity
- `created_at TIMESTAMPTZ`
- `updated_at TIMESTAMPTZ`

## Trigger Mechanism

Options (in order of preference):
1. **Supabase pg_cron** — runs inside Postgres, no external dependency
2. **Railway cron** — external HTTP trigger to a consolidation endpoint
3. **External cron service** — Render, Fly.io, or GitHub Actions calling an endpoint

Recommended: Supabase `pg_cron` calls a Postgres function that inserts a row into a `consolidation_queue` table. The MCP server polls this queue on startup and periodically, or a separate worker process handles it.

Alternative: A `/consolidate` HTTP endpoint protected by a service role key, triggered by Railway cron or external scheduler.
