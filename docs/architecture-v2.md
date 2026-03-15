# MCP Brain v2 — Architecture & Implementation Roadmap

## Vision

**"The memory layer that gets smarter while you sleep."**

MCP Brain is a personal AI memory server that works across every AI platform via MCP protocol. Unlike competitors that bolt memory onto agent frameworks (Letta) or gate graph intelligence behind $249/mo (Mem0), MCP Brain is MCP-native from day one, with neuroscience-inspired consolidation that no competitor implements.

## Positioning vs Competitors

| Dimension | MCP Brain | Mem0 | Letta | Zep |
|-----------|-----------|------|-------|-----|
| **Core identity** | MCP-native memory | Memory API | Agent runtime | Temporal KG |
| **Conflict resolution** | On-write + nightly consolidation | On-write (2 LLM calls) | LLM self-manages | LLM + temporal |
| **Consolidation** | Neuroscience-inspired nightly | None | Recursive summarization | None |
| **Graph memory** | Postgres-native ($7.99) | Neo4j ($249/mo) | None | Graphiti |
| **Auto-extraction** | Claude Code hooks + system prompt | Two-phase pipeline | LLM decides | Yes |
| **Pricing** | $7.99/mo | $19-249/mo | Credits | Credits |
| **Benchmarks** | Transparent, reproducible | Disputed (LoCoMo controversy) | N/A | Disputed |

## Architecture Overview

```
┌──────────────────────────────────────────────────────────┐
│                    MCP Clients                            │
│  Claude Code / Desktop / Cursor / ChatGPT / Codex / VS Code │
└────────────────────────┬─────────────────────────────────┘
                         │ POST /mcp/ (Streamable HTTP)
                         │ Authorization: Bearer <JWT>
                         ▼
┌──────────────────────────────────────────────────────────┐
│              FastMCP Server (Python + uvicorn)            │
│                                                          │
│  MCP Tools (10):                                         │
│    create_memory (+ on-write conflict detection)         │
│    search_memories / list_memories / delete_memory        │
│    brain_stats / list_banks / create_bank                │
│    import_memories / get_conflicts / get_entities         │
│                                                          │
│  Consolidation Worker:                                   │
│    /api/consolidate (service-key protected)               │
│    Importance scoring, dedup, conflict resolution         │
│    Entity extraction, memory archival                     │
│                                                          │
│  Stripe Webhooks:                                        │
│    /api/stripe/webhook                                    │
└───────┬──────────────────┬───────────────┬───────────────┘
        │                  │               │
        ▼                  ▼               ▼
  ┌────────────┐  ┌──────────────┐  ┌───────────┐
  │ OpenAI API │  │  Supabase    │  │  Stripe   │
  │ Embeddings │  │  Postgres    │  │  Billing  │
  │            │  │  + pgvector  │  │           │
  └────────────┘  └──────────────┘  └───────────┘
```

## New Database Schema (Migration 005)

### New columns on `memories`:
```sql
ALTER TABLE memories ADD COLUMN access_count INTEGER DEFAULT 0;
ALTER TABLE memories ADD COLUMN last_accessed_at TIMESTAMPTZ;
ALTER TABLE memories ADD COLUMN importance_score FLOAT DEFAULT 0.0;
ALTER TABLE memories ADD COLUMN archived_at TIMESTAMPTZ;
ALTER TABLE memories ADD COLUMN archived_reason TEXT;
ALTER TABLE memories ADD COLUMN superseded_by UUID REFERENCES memories(id);
ALTER TABLE memories ADD COLUMN version INTEGER DEFAULT 1;
```

### New table: `consolidation_log`
```sql
CREATE TABLE consolidation_log (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    bank_id UUID NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('merge', 'archive', 'update_score', 'extract_entity', 'resolve_conflict')),
    memory_ids UUID[] NOT NULL,
    details JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_consolidation_log_user ON consolidation_log(user_id, created_at DESC);
```

### New table: `memory_entities`
```sql
CREATE TABLE memory_entities (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    bank_id UUID NOT NULL,
    entity_name TEXT NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('person', 'organization', 'place', 'project', 'topic')),
    facts JSONB DEFAULT '[]',  -- [{content, memory_id, created_at}]
    memory_ids UUID[] DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, bank_id, entity_name, entity_type)
);
CREATE INDEX idx_entities_user_bank ON memory_entities(user_id, bank_id);
CREATE INDEX idx_entities_name ON memory_entities USING GIN(to_tsvector('english', entity_name));
```

### Update `profiles`:
```sql
ALTER TABLE profiles ADD COLUMN last_consolidation_at TIMESTAMPTZ;
```

## Feature Specifications

### 1. On-Write Conflict Detection

**Architecture Decision:** Hybrid approach — lightweight embedding-only detection on write (no LLM cost), with LLM-powered resolution deferred to consolidation.

**Flow:**
```
create_memory(content) →
  1. Generate embedding (existing)
  2. Query top-5 similar memories WHERE cosine > 0.85 AND bank_id = X
  3. IF similar found:
     a. Return conflict info in response (memory_ids, similarity scores, content previews)
     b. Let MCP client decide: replace, enrich, or keep both
     c. If client provides action: execute it
     d. If no action: insert as new, flag for consolidation review
  4. Insert memory
```

**Why no LLM on write:** Mem0 spends 2 LLM calls per `memory.add()`. At $0.003/1K tokens, this costs ~$0.01 per memory. For 50 memories/day = $0.50/day = $15/month — nearly 2x our subscription price. Embedding-only detection is free (already have the vector, just a SQL query). The MCP client's LLM can do the classification for free since it already has conversation context.

**New MCP tool response format for create_memory:**
```json
{
  "status": "created",
  "memory_id": "uuid",
  "conflicts": [
    {
      "memory_id": "existing-uuid",
      "content": "My wife is Maria",
      "similarity": 0.92,
      "suggestion": "This may contradict or update an existing memory"
    }
  ]
}
```

### 2. Nightly Consolidation

**Architecture Decision:** Railway cron → HTTP endpoint with service role key auth.

**Why not pg_cron:** Consolidation needs LLM calls for ambiguous conflict resolution and entity extraction. pg_cron is SQL-only — can't call external APIs. The HTTP endpoint approach keeps all Python logic in one place.

**Why not separate worker:** Adds infrastructure complexity. A simple HTTP endpoint called by Railway cron (or any external scheduler) is the simplest solution that works.

**Endpoint:** `POST /api/consolidate`
- Auth: `X-Service-Key` header matching `SUPABASE_SERVICE_ROLE_KEY`
- Processes all users with activity since their `last_consolidation_at`
- Per-user pipeline:

```
Phase 1: Score (pure SQL, no LLM)
  - importance = recency_decay(days_old) × (1 + 0.1 × access_count) × (1 + 0.05 × entity_count)
  - Update importance_score on all memories

Phase 2: Deduplicate (SQL + embeddings)
  - Find pairs with cosine > 0.90 within same bank
  - Group into clusters
  - Keep highest-scored memory, archive others with superseded_by pointer

Phase 3: Resolve Conflicts (LLM for ambiguous pairs only)
  - Find pairs with cosine 0.80-0.90 AND shared entities
  - Pre-filter: if timestamps differ by >30 days and same entity type → likely update
  - LLM classify remaining as: UPDATE (newer wins), MERGE (combine), KEEP_BOTH
  - Execute resolution, log to consolidation_log

Phase 4: Extract Entities (LLM)
  - For memories without entity metadata:
    - Batch 10 memories per LLM call
    - Extract {entity_name, entity_type, relationship}
    - Upsert into memory_entities table

Phase 5: Archive (pure SQL)
  - Memories with importance_score < 0.1 AND age > 90 days AND access_count = 0
  - Set archived_at, archived_reason = 'low_importance_decay'
  - Archived memories excluded from search but recoverable
```

**Cost per consolidation run (1,000 active users):**
| Phase | LLM Calls | Cost |
|-------|-----------|------|
| Score | 0 | $0 |
| Deduplicate | 0 | $0 |
| Conflicts | ~50/user × 1000 = 50K | ~$5-15 (Haiku) |
| Entities | ~100/user × 1000 = 100K | ~$10-30 (Haiku) |
| Archive | 0 | $0 |
| **Total/night** | | **~$15-45** |

### 3. Entity Extraction (Postgres-Native Graph)

**Architecture Decision:** Postgres JSONB + `memory_entities` table instead of Neo4j.

**Why not Neo4j:** Adds Docker dependency, new infrastructure, operational complexity. For our use case (entity lookup, 1-hop relationships), Postgres JSONB is sufficient. If we outgrow it, we can migrate entities to Neo4j later — the `memory_entities` table schema maps cleanly to graph nodes.

**Entity types:** person, organization, place, project, topic

**How entities are used in search:**
```sql
-- Find memories related to an entity
SELECT m.* FROM memories m
JOIN memory_entities e ON m.id = ANY(e.memory_ids)
WHERE e.user_id = $1 AND e.entity_name ILIKE $2 AND m.archived_at IS NULL;

-- Find related entities (1-hop)
SELECT DISTINCT e2.* FROM memory_entities e1
JOIN memory_entities e2 ON e1.memory_ids && e2.memory_ids
WHERE e1.user_id = $1 AND e1.entity_name = $2 AND e2.id != e1.id;
```

**New MCP tool: `get_entities`**
```python
@mcp.tool()
async def get_entities(
    query: str | None = None,  # Search entity names
    entity_type: str | None = None,  # Filter by type
    token: AccessToken = CurrentAccessToken(),
) -> str:
    """List known entities and their associated facts."""
```

### 4. Bulk Import

**New MCP tool: `import_memories`**
```python
@mcp.tool()
async def import_memories(
    memories: list[dict],  # [{content, memory_type?, tags?, metadata?}]
    deduplicate: bool = True,
    token: AccessToken = CurrentAccessToken(),
) -> str:
    """Import multiple memories at once. Deduplicates by default."""
```

**Flow:**
1. Validate all memories (content length, types, tags)
2. Generate embeddings in batch (OpenAI supports batch embedding)
3. For each: check similarity against existing (if deduplicate=True)
4. Insert non-duplicates
5. Return: created count, skipped count, conflict list

### 5. Stripe Integration

**Webhook endpoint:** `POST /api/stripe/webhook`

**Events handled:**
- `checkout.session.completed` → Create/update subscription, set profile status = 'active'
- `customer.subscription.updated` → Update status (active, past_due, etc.)
- `customer.subscription.deleted` → Set status = 'canceled', downgrade limits
- `invoice.payment_failed` → Set status = 'past_due', notify via metadata flag

**Implementation:**
```python
# In main.py, add Starlette route:
app.routes.insert(0, Route("/api/stripe/webhook", stripe_webhook_handler, methods=["POST"]))

# Webhook handler verifies Stripe signature, dispatches by event type
# Uses SUPABASE_SERVICE_ROLE_KEY for direct DB updates (bypasses RLS)
```

**Checkout flow:**
1. Frontend sends user to Stripe Checkout with `client_reference_id = user_id`
2. Stripe redirects to success URL
3. Webhook fires `checkout.session.completed`
4. Handler creates subscription record + updates profile status

### 6. Platform Integration Guide

| Platform | Install Method | Auto-Extraction |
|----------|---------------|-----------------|
| **Claude Code** | `claude mcp add brain --transport http URL` | Yes — PostToolUse + SessionEnd hooks |
| **Claude Desktop** | `claude_desktop_config.json` mcpServers entry | System prompt instruction only |
| **Cursor** | Settings → MCP Servers or `.cursor/mcp.json` | System prompt instruction only |
| **VS Code (Copilot)** | `.vscode/mcp.json` | System prompt instruction only |
| **ChatGPT** | Developer Mode → MCP server config | System prompt instruction only |
| **Codex CLI** | `codex mcp add` or config file | System prompt instruction only |

**Claude Code auto-extraction hook (`.claude/hooks.json`):**
```json
{
  "hooks": {
    "Stop": [{
      "type": "command",
      "command": "python3 -c \"import sys, json, httpx; ... extract and POST to MCP Brain\""
    }]
  }
}
```

**System prompt instruction (all platforms):**
```
You are connected to MCP Brain, the user's personal memory. When the user shares
facts about themselves, preferences, decisions, or important context, use
create_memory to store it. When the user asks about something they mentioned
before, use search_memories. Always check for conflicts in the response.
```

### 7. Memory Quality Benchmarks

**Benchmark suite (to build):**
1. **Retrieval accuracy** — custom test set: 100 stored memories, 50 queries, measure Precision@5 and MRR
2. **Conflict detection rate** — 30 contradictory pairs, measure detection rate
3. **Temporal reasoning** — 20 time-ordered facts, measure correct ordering
4. **Deduplication accuracy** — 50 near-duplicate pairs + 50 similar-but-different, measure F1
5. **Consolidation quality** — before/after consolidation: signal-to-noise ratio improvement

**Website metrics (hero section):**
- "X% retrieval accuracy on [benchmark]"
- "Sub-Yms search latency (p95)"
- "Z% conflict detection rate"

## Implementation Roadmap

### Day 1: Core Infrastructure
- [ ] Migration 005: new columns + tables (consolidation_log, memory_entities)
- [ ] Refactor: extract shared UUID parsing utility across db modules
- [ ] On-write conflict detection in create_memory
- [ ] Access tracking (access_count, last_accessed_at) on search
- [ ] Stripe webhook endpoint + checkout flow
- [ ] Update tests for all changes

### Day 2: Intelligence Layer
- [ ] Consolidation endpoint (/api/consolidate)
- [ ] Importance scoring algorithm (Phase 1)
- [ ] Near-duplicate detection + merge (Phase 2)
- [ ] LLM-based conflict resolution (Phase 3)
- [ ] Entity extraction pipeline (Phase 4)
- [ ] Memory archival with soft delete (Phase 5)
- [ ] Consolidation audit logging
- [ ] New MCP tools: get_entities, import_memories
- [ ] Tests for consolidation pipeline

### Day 3: Polish & Ship
- [ ] Platform installation docs (Claude Code, Cursor, ChatGPT, etc.)
- [ ] Auto-extraction hook for Claude Code
- [ ] Frontend: Stripe checkout button, memory stats, consolidation log view
- [ ] Benchmark suite (basic: retrieval accuracy, conflict detection)
- [ ] Railway deployment: add cron job for nightly consolidation
- [ ] Security review of new endpoints
- [ ] Test with friends, iterate

## Key Technical Decisions Log

1. **On-write: embedding-only, no LLM** — Saves $15/month per user in LLM costs. MCP client resolves conflicts for free.
2. **Railway cron, not pg_cron** — Consolidation needs LLM calls, which requires Python, not SQL.
3. **Postgres JSONB, not Neo4j** — No new infrastructure. Entity lookup + 1-hop relationships work fine with arrays + joins.
4. **Soft delete, never hard delete** — `archived_at` + `archived_reason`. 30-day recovery window.
5. **Incremental consolidation** — Only process memories since last run. Scales to 100K+ memories.
6. **Haiku for consolidation LLM calls** — Cheapest model that can classify conflicts and extract entities.
7. **Service role key for consolidation auth** — Not user JWT. Consolidation runs as system process.

## Council Debate Summary (Decision Validation)

A 4-member council (Architect, Designer, Engineer, Researcher) debated all 3 decisions:

### Decision 1: On-Write Conflict Detection — SPLIT 2-2

**For batch (Architect + Engineer):** Write-path latency is sacred. 200-500ms added to every create is unacceptable. Conflicts persisting 12 hours costs nothing. Keep writes deterministic and testable.

**For on-write (Designer + Researcher):** Trust is destroyed when "my wife is Margaret" still returns "Maria" hours later. Every production system (Mem0, Zep, ChatGPT) does it on-write. The researcher cited evidence: Mem0's paper, Zep's Graphiti paper, ChatGPT reverse-engineering all show on-write resolution.

**Resolution:** Our hybrid design satisfies both camps. Embedding-only similarity search on write (~10ms pgvector query, no LLM) detects conflicts immediately. LLM-powered resolution (expensive, ambiguous cases) defers to nightly batch. Fast writes + immediate detection + deferred intelligence.

### Decision 2: Consolidation Trigger — UNANIMOUS: Railway cron → HTTP endpoint

All 4 agreed. pg_cron eliminated on capability (SQL-only). Separate worker eliminated on operational overhead (2-3 day timeline). HTTP endpoint reuses existing infrastructure.

### Decision 3: Entity Extraction — UNANIMOUS: Postgres JSONB, not Neo4j

All 4 agreed strongly. Key evidence from researcher: Mem0's graph variant (Neo4j) achieves only ~2% higher accuracy while doubling token footprint. The designer adds: structure JSONB with entity references (`{subject, relation, object}`) for clean future migration path. The engineer: "I've led a Neo4j migration and I've led a Neo4j removal. The removal was harder."
